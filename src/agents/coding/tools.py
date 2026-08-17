"""Coding agent tools — repo discovery, HITL file proposals, dev plan."""
from __future__ import annotations

import json as _json_module
import re as _re_module
import subprocess
from pathlib import Path
from typing import Dict, Any, List

from langchain_core.tools import tool

from src.agents.coding.pending import FileChange, pending_changes, dev_plan, recent_tools, _ANALYSIS_TOOLS

from src.utils.paths import get_projects_dir


@tool("dev_plan_create")
def dev_plan_create(steps: List[str]) -> Dict[str, Any]:
    """
    Creates and displays a visible plan (todo list) before starting a coding task.
    ALWAYS call this first, before reading files or proposing any changes.
    Steps should be concrete actions (ex: "Lire src/app.py", "Ajouter route /health").

    Args:
        steps: ordered list of steps to accomplish (3–8 items)
    Returns:
        {"status": "ok", "count": N}
    """
    if not steps:
        return {"status": "error", "error": "steps cannot be empty"}

    if dev_plan.steps:
        done = sum(1 for s in dev_plan.steps if s.done)
        return {
            "status": "already_exists",
            "message": "Un plan existe déjà. Continue avec les étapes existantes, n'en crée pas un nouveau.",
            "steps": [s.label for s in dev_plan.steps],
            "done": done,
            "remaining": len(dev_plan.steps) - done,
        }

    dev_plan.create(steps)
    return {"status": "ok", "count": len(steps)}


@tool("dev_plan_update")
def dev_plan_update(steps: List[str], reason: str) -> Dict[str, Any]:
    """
    Replaces the remaining steps of the current plan when what you learned makes it wrong.
    Steps already ticked stay ticked and must be repeated verbatim at the head of `steps`;
    everything after them is rewritten. Use it when analysis reveals the plan missed a file,
    or when a step turned out to be unnecessary — a plan you cannot revise makes you either
    lie about a step or abandon the task.

    Args:
        steps: the FULL new list — completed steps first, unchanged, then the revised rest
        reason: one line saying what you learned that made the old plan wrong
    Returns:
        {"status": "ok", "count": N, "kept_done": M}
    """
    if not steps:
        return {"status": "error", "error": "steps ne peut pas être vide."}
    if not reason.strip():
        return {"status": "error",
                "error": "reason est obligatoire : dis ce que tu as appris qui invalide le plan."}

    faits = [s.label for s in dev_plan.steps if s.done]
    if steps[:len(faits)] != faits:
        return {
            "status": "error",
            "error": ("Les étapes déjà cochées doivent être reprises telles quelles, en tête et "
                      f"dans l'ordre. Attendu au début : {faits}. Réécris seulement la suite."),
        }

    dev_plan.replace(steps, done_count=len(faits))
    return {"status": "ok", "count": len(steps), "kept_done": len(faits), "reason": reason}


_TODO_MARKERS = (
    # Python / shell
    "# TODO", "# FIXME", "# HACK", "# XXX",
    "# A compléter", "# A completer", "# à compléter", "# Compléter", "# FILL",
    # JS / TS / Java / C / Go / Rust
    "// TODO", "// FIXME", "// HACK", "// XXX",
    "// A compléter", "// A completer", "// à compléter", "// Compléter",
    "/* TODO", "/* FIXME",
    # HTML / JSX templates
    "<!-- TODO", "{/* TODO",
)


def _verify_notebook_cell(path: str, cell_index: int, must_contain: str = "") -> tuple[bool, str]:
    """Reads the actual notebook file and checks the cell is non-trivial."""
    import json
    from pathlib import Path as _Path
    try:
        with open(path, encoding="utf-8") as f:
            nb = json.load(f)
    except Exception as e:
        return False, f"Impossible de lire le notebook : {e}"

    cells = nb.get("cells", [])
    if not (0 <= cell_index < len(cells)):
        return False, f"Cellule {cell_index} introuvable dans le notebook ({len(cells)} cellules)"

    source = "".join(cells[cell_index].get("source", []))

    if not source.strip():
        return False, f"Cellule {cell_index} est vide — aucun code n'a été écrit"

    for marker in _TODO_MARKERS:
        if marker.lower() in source.lower():
            return False, f"Cellule {cell_index} contient encore '{marker}' — la complétion n'a pas eu lieu"

    if must_contain and must_contain not in source:
        return False, f"Cellule {cell_index} ne contient pas '{must_contain}' — vérifie le contenu écrit"

    return True, ""


def _verify_file_written(path: str, must_contain: str = "") -> tuple[bool, str]:
    """Checks a file exists, has non-trivial content, no TODO markers, and optionally a keyword."""
    from pathlib import Path as _Path
    p = _Path(path)
    if not p.exists():
        return False, f"Fichier '{path}' introuvable sur le disque — la modification n'a pas été appliquée"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"Impossible de lire '{path}' : {e}"

    if not content.strip():
        return False, f"Fichier '{path}' est vide — aucun code n'a été écrit"

    for marker in _TODO_MARKERS:
        if marker.lower() in content.lower():
            return False, f"Fichier '{path}' contient encore '{marker}' — la complétion n'a pas eu lieu"

    if must_contain and must_contain not in content:
        return False, f"Fichier '{path}' ne contient pas '{must_contain}'"

    return True, ""


@tool("dev_plan_step_done")
def dev_plan_step_done(
    step_index: int,
    proof_type: str,
    proof_path: str = "",
    proof_cell_index: int = -1,
    proof_contains: str = "",
) -> Dict[str, Any]:
    """
    Marks a plan step as completed. Performs a REAL verification on disk — cannot be faked.

    Args:
        step_index:        zero-based index of the completed step
        proof_type:        what kind of proof to check:
                             "analysis"            — a read tool was called (notebook_read, local_read_file…)
                             "notebook_cell_edited" — a notebook cell was actually modified on disk
                             "file_written"         — a file was actually written to disk
                             "shell_ran"            — a shell command ran with exit_code 0
        proof_path:        required for "notebook_cell_edited" and "file_written" — absolute path
        proof_cell_index:  required for "notebook_cell_edited" — zero-based cell index
        proof_contains:    optional substring that must be present in the cell/file content

    Returns:
        {"status": "ok", "step": label, "remaining": N}
        {"status": "error", "error": "…"}  ← real check failed, do the actual work first
    """
    steps = dev_plan.steps
    if not (0 <= step_index < len(steps)):
        return {"status": "error", "error": f"Index {step_index} hors limites (plan : {len(steps)} étapes)"}

    if not proof_type or not proof_type.strip():
        return {"status": "error", "error": "proof_type est obligatoire. Indique 'analysis', 'notebook_cell_edited', 'file_written' ou 'shell_ran'."}

    # ── Real verification ──────────────────────────────────────────────────────
    ok, err = True, ""

    if proof_type == "analysis":
        if not recent_tools.any_analysis():
            ok, err = False, (
                "Aucun outil d'analyse n'a été appelé depuis la dernière étape. "
                "Appelle notebook_read, local_read_file ou dev_explain d'abord."
            )

    elif proof_type == "notebook_cell_edited":
        if not proof_path:
            return {"status": "error", "error": "proof_path est requis pour proof_type='notebook_cell_edited'"}
        if proof_cell_index < 0:
            return {"status": "error", "error": "proof_cell_index est requis pour proof_type='notebook_cell_edited'"}
        if not recent_tools.cell_was_edited(proof_path, proof_cell_index):
            ok, err = False, (
                f"La cellule {proof_cell_index} de '{proof_path}' n'a pas été éditée (notebook_edit_cell non accepté). "
                "Appelle notebook_edit_cell et assure-toi que l'utilisateur accepte."
            )
        else:
            ok, err = _verify_notebook_cell(proof_path, proof_cell_index, proof_contains)

    elif proof_type == "file_written":
        if not proof_path:
            return {"status": "error", "error": "proof_path est requis pour proof_type='file_written'"}
        if not recent_tools.file_was_written(proof_path):
            ok, err = False, (
                f"'{proof_path}' n'a pas été écrit (propose_file_change non accepté). "
                "Appelle propose_file_change et assure-toi que l'utilisateur accepte."
            )
        else:
            ok, err = _verify_file_written(proof_path, proof_contains)

    elif proof_type == "shell_ran":
        if not recent_tools.shell_succeeded():
            ok, err = False, (
                "Aucune commande shell n'a terminé avec exit_code=0 depuis la dernière étape. "
                "Appelle shell_run et assure-toi que la commande réussit."
            )

    else:
        return {"status": "error", "error": f"proof_type inconnu : '{proof_type}'. Valeurs acceptées : analysis, notebook_cell_edited, file_written, shell_ran"}

    if not ok:
        return {"status": "error", "error": f"Vérification échouée : {err}"}

    # ── Mark done ──────────────────────────────────────────────────────────────
    changed = dev_plan.check(step_index)
    label = steps[step_index].label
    if not changed:
        return {"status": "already_done", "step": label}

    recent_tools.clear()
    return {"status": "ok", "step": label, "remaining": sum(1 for s in dev_plan.steps if not s.done)}


@tool("dev_explain")
def dev_explain(message: str) -> Dict[str, Any]:
    """
    Presents an analysis summary to the user BEFORE making any file changes.
    Call this after reading files and before the first propose_file_change.
    Use it to explain: what you found, what bugs exist and why, what you will change and how.

    Args:
        message: clear explanation in French (markdown supported) — bugs found, root cause, fix strategy
    Returns:
        {"status": "ok"}
    """
    if not message.strip():
        return {"status": "error", "reason": "Message vide interdit. Fournis une explication détaillée : ce que tu as trouvé, pourquoi, et ce que tu vas changer."}
    # The actual display is handled by the UI via the progress callback
    return {"status": "ok"}


#: Questions acceptées en un seul appel. Au-delà, ce n'est plus une clarification.
MAX_QUESTIONS = 10


def normaliser_questions(brut: Any) -> List[Dict[str, Any]]:
    """Ramène l'argument `questions` à une liste de questions, ou lève.

    UNE CHAÎNE N'EST PAS UNE LISTE DE QUESTIONS. Le modèle a passé
    `questions="Toutes les sections…"` ; le questionnaire, qui itère sur son
    argument, a énuméré les CARACTÈRES — 1312 questions d'une lettre chacune,
    et un terminal bloqué. Python itère volontiers sur une chaîne : c'est à la
    frontière de valider, pas au consommateur de deviner.
    """
    if isinstance(brut, str):
        texte = brut.strip()
        if not texte:
            raise ValueError("questions vide.")
        # Une chaîne vaut UNE question, jamais une par caractère.
        return [{"question": texte}]
    if not isinstance(brut, (list, tuple)):
        raise ValueError(
            f"questions doit être une liste, reçu {type(brut).__name__}. "
            'Format attendu : [{"question": "…", "choices": ["A", "B"]}]')
    propres: List[Dict[str, Any]] = []
    for item in brut:
        if isinstance(item, dict):
            libelle = str(item.get("question", "")).strip()
            if not libelle:
                continue
            entree: Dict[str, Any] = {"question": libelle}
            choix = item.get("choices")
            if isinstance(choix, (list, tuple)) and choix:
                entree["choices"] = [str(c) for c in choix]
            propres.append(entree)
        elif isinstance(item, str) and item.strip():
            propres.append({"question": item.strip()})
    if not propres:
        raise ValueError(
            'Aucune question exploitable. Format attendu : '
            '[{"question": "…", "choices": ["A", "B"]}]')
    if len(propres) > MAX_QUESTIONS:
        raise ValueError(
            f"{len(propres)} questions demandées, maximum {MAX_QUESTIONS}. "
            "Regroupe l'essentiel : au-delà, ce n'est plus une clarification.")
    return propres


@tool("ask_clarification")
def ask_clarification(questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Asks the user one or more questions and WAITS for the answers, then continues
    the same run — the plan, the files already written and the whole context are kept.

    Use it when a design choice, a naming or an approach is genuinely undecidable
    from the task and the files. Never ask in plain text: a plain-text question ends
    the run, and everything done so far has to be redone from scratch.

    Args:
        questions: list of {"question": "...", "choices": ["A", "B", "C"]}.
                   Provide 3-5 choices when the options are known; omit `choices`
                   for an open question.
    Returns:
        {"answers": {question: answer, ...}} — act on them immediately.
    """
    try:
        normaliser_questions(questions)
    except ValueError as e:
        return {"status": "error", "reason": str(e)}
    # Le vrai questionnaire est rendu par l'UI, qui remplace ce résultat par les
    # réponses (même canal que la revue de fichier). Sans UI branchée, on rend un
    # état explicite plutôt qu'une attente qui ne viendra jamais.
    return {"status": "no_ui",
            "message": ("Aucune interface pour poser la question. Choisis l'option "
                        "la plus raisonnable, signale-la dans dev_explain, et continue.")}


@tool("find_git_repos")
def find_git_repos(root: str = "") -> Dict[str, Any]:
    """
    Scans the filesystem to find local git repositories.
    Use when the user wants to work on a local project but hasn't specified the path.
    PREREQUISITE: dev_plan_create() must have been called first.

    Args:
        root: directory to scan from (default: $HOME). Use "" for HOME.
    Returns:
        {"status": "ok", "repos": [{"path", "name", "branch"}, ...]}
    """
    if not dev_plan.steps:
        return {
            "status": "error",
            "error": "Appelle d'abord dev_plan_create() pour créer un plan avant de commencer.",
        }

    default_base = get_projects_dir()
    base = Path(root) if root else default_base
    if not base.exists():
        return {"status": "error", "error": f"Dossier introuvable : {root}"}

    repos = []
    try:
        result = subprocess.run(
            [
                "find", str(base),
                "-name", ".git", "-type", "d",
                "-not", "-path", "*/.git/*",
                "-maxdepth", "6",
            ],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            repo_path = Path(line).parent
            branch = ""
            try:
                br = subprocess.run(
                    ["git", "-C", str(repo_path), "branch", "--show-current"],
                    capture_output=True, text=True, timeout=3,
                )
                branch = br.stdout.strip()
            except Exception:
                pass
            repos.append({
                "path": str(repo_path),
                "name": repo_path.name,
                "branch": branch or "unknown",
            })
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "repos": repos, "note": "scan interrompu (timeout)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

    repos.sort(key=lambda r: r["path"])
    return {"status": "ok", "count": len(repos), "repos": repos}


# `browser_screenshot` vivait ici, au-dessus de `src/infra/browser.py` : un
# Playwright piloté à la main, une capture, et un audit JS de six règles écrites
# en dur (texte tronqué, hors viewport, section vide, image cassée…).
#
# Il est remplacé par le serveur MCP Playwright, qui rend l'arbre
# d'accessibilité, le clic, la saisie de formulaire, les erreurs de console et
# les requêtes réseau échouées — là où celui-ci ne savait que photographier puis
# deviner. Six règles maintenues à la main ne rattraperont jamais un navigateur
# qu'on peut interroger.
#
# La bascule n'a été faite qu'une fois le routage MESURÉ, pas à l'annonce du
# remplaçant : cf. tests/test_mcp_routing_specialist.py.


@tool("project_graph_query")
def project_graph_query(project_path: str, symbol: str) -> dict:
    """
    Find where a function/class/module is defined in a project's knowledge graph.
    Requires graph.json generated by `/graph` command (graphify extract).
    Much faster than local_grep for symbol lookup — returns file + line in one call.

    Args:
        project_path: project path (absolute, relative to cwd, or project name like "ai-agent")
        symbol: function, class, or module name to find (partial match supported)
    Returns:
        {"matches": [{"label", "source_file", "source_location", "type"}], "callers": [...]}
        {"status": "no_graph", "hint": ...} if graph.json not found
    """
    import json
    from pathlib import Path as _P

    # Path resolution: absolute → cwd-relative → project name lookup
    p = _P(project_path).expanduser()
    if not p.is_absolute():
        try:
            from src.agents.shell.tools import _cwd as shell_cwd
            candidate = _P(shell_cwd) / project_path
            if candidate.is_dir():
                p = candidate
            else:
                from src.utils.paths import get_projects_dir
                p = get_projects_dir() / project_path
        except Exception:
            pass

    # graphify writes graph.json to <project>/graphify-out/ by default
    graph_path = p / "graphify-out" / "graph.json"
    if not graph_path.exists():
        graph_path = p / "graph.json"  # fallback: root-level
    if not graph_path.exists():
        return {
            "status": "no_graph",
            "project": str(p),
            "hint": f"Lance /graph {p.name} depuis axon pour générer le graph (subprocess direct, zéro token).",
        }

    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "error", "error": str(e)}

    nodes = {n["id"]: n for n in data.get("nodes", [])}
    edges = data.get("links", [])  # NetworkX node_link_graph uses "links"

    needle = symbol.lower()
    matches = [
        {
            "label": n.get("label"),
            "source_file": n.get("source_file"),
            "source_location": n.get("source_location"),
            "type": n.get("type"),
        }
        for n in nodes.values()
        if needle in n.get("label", "").lower()
    ][:10]

    if not matches:
        return {"status": "not_found", "symbol": symbol, "project": str(p)}

    match_ids = {
        n["id"] for n in nodes.values() if needle in n.get("label", "").lower()
    }
    callers = [
        {
            "from": nodes.get(e["source"], {}).get("label"),
            "file": nodes.get(e["source"], {}).get("source_file"),
        }
        for e in edges if e.get("target") in match_ids
    ][:5]

    return {"status": "ok", "symbol": symbol, "matches": matches, "callers": callers}


# load_skill vit dans src/skills/, partagé avec l'orchestrateur ; seule la portée
# les distingue. Plus de repli : les skills .md sont l'unique source des guides.
from src.skills.tools import make_load_skill

load_skill = make_load_skill("coding")


#: Une balise ouvrante en tête d'un contenu qui ne devrait pas en avoir. C'est la
#: signature d'un backend qui a sérialisé une structure en XML au lieu de la
#: rendre telle quelle.
_BALISE_EN_TETE = _re_module.compile(r"^\s*<[a-zA-Z][\w.-]*>")


def _contenu_invalide(p: Path, content: str) -> str:
    """Refuse un contenu que son extension rend manifestement faux.

    Relevé sur un vrai build : `public/config.json` a été écrit avec
    `<demoUrl>https://demo.axon.ai/run</demoUrl><license>MIT</license>` — du XML
    sous un nom `.json`. Le backend avait sérialisé la structure en balises au
    lieu de rendre la chaîne. L'agent a ensuite brûlé une dizaine d'étapes en
    `xxd` et `cat -A` à chercher un problème d'encodage, avant de renoncer et de
    déplacer la config dans un module TypeScript.

    Le coût n'est pas l'écriture ratée — c'est l'enquête qu'elle déclenche. Un
    refus IMMÉDIAT qui NOMME la cause épargne les dix étapes : l'agent sait
    quoi corriger au lieu de devoir le déduire.

    On ne valide que ce qui se valide sans ambiguïté. Un `.md` ou un `.tsx`
    accepte à peu près tout ; un `.json` non analysable est faux, sans discussion.
    """
    suffixe = p.suffix.lower()

    if suffixe == ".json":
        try:
            _json_module.loads(content)
        except ValueError as exc:
            indice = ""
            if _BALISE_EN_TETE.match(content):
                indice = (" Le contenu commence par une balise : ton backend a "
                          "probablement sérialisé la structure en XML. Rends le "
                          "JSON comme une CHAÎNE de caractères, littéralement.")
            return (f"Contenu refusé : {p.name} porte l'extension .json mais "
                    f"n'est pas du JSON analysable ({exc}).{indice} "
                    "Rien n'a été écrit.")

    # Une balise en tête d'un fichier de code est le même symptôme, sans
    # analyseur pour le prouver. On le signale sans bloquer : un `.tsx` peut
    # légitimement commencer par du JSX.
    if suffixe in (".py", ".ts", ".js", ".css", ".yaml", ".yml", ".toml", ".env"):
        if _BALISE_EN_TETE.match(content):
            return (f"Contenu refusé : {p.name} commence par une balise XML, ce "
                    "qu'un fichier de ce type ne fait pas. Ton backend a "
                    "probablement sérialisé le contenu au lieu de le rendre tel "
                    "quel. Rien n'a été écrit.")
    return ""


@tool("propose_file_change")
def propose_file_change(path: str, content: str, description: str) -> Dict[str, Any]:
    """
    Writes a file WHOLE — use it only to CREATE a file, or to rewrite one end to end.
    To change part of an existing file, use edit_file: it costs the size of the change,
    not the size of the file, and cannot silently drop the parts you did not retype.
    The user is shown a diff and approves, rejects, or refines.

    Args:
        path: absolute path of the file to create or modify
        content: complete new content for the file
        description: one-line description of what this change does (ex: "Ajoute la route /health")
    Returns:
        {"status": "proposed", "path": path, "awaiting_confirmation": true}
    """
    if not dev_plan.steps:
        return {
            "status": "error",
            "error": "Tu dois d'abord appeler dev_plan_create() pour créer un plan avant de proposer des fichiers.",
        }

    p = Path(path)

    refus = _contenu_invalide(p, content)
    if refus:
        return {"status": "error", "error": refus}

    original = ""
    if p.exists() and p.is_file():
        try:
            original = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    pending_changes.add(FileChange(
        path=path,
        original=original,
        proposed=content,
        description=description,
    ))

    return {
        "status": "proposed",
        "path": path,
        "is_new_file": not bool(original),
        "description": description,
        "awaiting_confirmation": True,
    }


def _base_content(path: str) -> tuple[str, str] | None:
    """Rend (original_vrai, contenu_courant) pour une édition, ou None si absent.

    Une proposition déjà en attente sur ce chemin fait foi sur le disque : sans
    ça, deux éditions successives du même fichier avant la revue perdraient la
    première — `PendingStore.add` remplace par chemin.
    """
    for change in pending_changes.items:
        if change.path == path:
            return change.original, change.proposed
    p = Path(path)
    if not (p.exists() and p.is_file()):
        return None
    try:
        contenu = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return contenu, contenu


@tool("edit_file")
def edit_file(path: str, old_string: str, new_string: str,
              description: str = "", replace_all: bool = False) -> Dict[str, Any]:
    """
    Changes PART of an existing file by replacing an exact fragment. Preferred way
    to modify anything that already exists — you send only the fragment, never the
    whole file, so a 500-line file costs the same as a 5-line one and the 495 lines
    you did not touch cannot be lost.

    `old_string` must match the file byte for byte, indentation included, and must
    be UNIQUE: add surrounding lines until it is, or pass replace_all=True to change
    every occurrence (renaming a symbol).

    Args:
        path: absolute path of an EXISTING file
        old_string: exact fragment to replace, copied from the file
        new_string: replacement fragment ("" deletes the fragment)
        description: one-line description of what this change does
        replace_all: replace every occurrence instead of requiring a unique match
    Returns:
        {"status": "proposed", "path": path, "replacements": N, "awaiting_confirmation": true}
    """
    if old_string == new_string:
        return {"status": "error",
                "error": "old_string et new_string sont identiques — il n'y a rien à changer."}

    base = _base_content(path)
    if base is None:
        return {"status": "error",
                "error": (f"'{path}' n'existe pas ou n'est pas lisible. edit_file modifie un "
                          "fichier existant ; pour en créer un, utilise propose_file_change.")}
    original, courant = base

    occurrences = courant.count(old_string)
    if occurrences == 0:
        return {"status": "error",
                "error": (f"Fragment introuvable dans '{path}'. Relis le fichier avec "
                          "local_read_file et copie le fragment exactement — espaces et "
                          "indentation compris.")}
    if occurrences > 1 and not replace_all:
        return {"status": "error",
                "error": (f"Fragment présent {occurrences} fois dans '{path}'. Ajoute des lignes "
                          f"autour pour le rendre unique, ou passe replace_all=True pour "
                          f"remplacer les {occurrences} occurrences.")}

    propose = (courant.replace(old_string, new_string) if replace_all
               else courant.replace(old_string, new_string, 1))

    pending_changes.add(FileChange(
        path=path,
        original=original,
        proposed=propose,
        description=description or f"Édition de {Path(path).name}",
    ))

    return {
        "status": "proposed",
        "path": path,
        "replacements": occurrences if replace_all else 1,
        "description": description,
        "awaiting_confirmation": True,
    }
