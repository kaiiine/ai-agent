"""Exécution séquentielle d'un projet par phases — réduit la consommation de tokens."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.agents.coding.task_decomposer import decompose, Phase

# Marqueurs d'échec détectables dans le résultat du specialist (FR + EN)
# La sentinelle fait foi ; les phrases ne sont qu'un filet pour l'existant.
# Une reformulation suffisait à rendre la détection aveugle.
from src.agents.coding.specialist import ECHEC_PREFIXE

_PHASE_FAILED_MARKERS = (
    ECHEC_PREFIXE.lower(),
    "impossible d'invoquer le modèle",
    "contexte trop volumineux",
    "cannot invoke the model",
    "context too large",
    "rate limit",
    "quota exceeded",
    "resource_exhausted",
    # Iteration limit reached = phase didn't finish → retry
    "tâche interrompue",
    "tache interrompue",
    "limite d'itérations",
    "iteration limit",
)

_PHASE_ITER_BUDGET = {
    "mistral": 30, "groq": 80, "gemini": 100,
    "ollama_cloud": 80, "ollama": 20,
}

# ── Pre-scaffold : détection framework + exécution hors LLM ──────────────────

# Commande pnpm create à lancer pour chaque framework détecté.
# Scaffold dans un sous-dossier de transit pour préserver spec.md, puis fusion
# à la racine. Le nom doit être un nom de paquet npm VALIDE : `.scaffold` était
# refusé (« name cannot start with a period »), et les cinq commandes échouaient.
# Nom de paquet npm valide : ni point ni underscore en tête.
SCAFFOLD_DIRNAME = "axon-scaffold"

_FRAMEWORK_SCAFFOLD_CMD = {
    "next":       "pnpm create next-app@latest axon-scaffold --yes --typescript --tailwind --app --src-dir --import-alias @/*",
    "vite-react": "pnpm create vite@latest axon-scaffold --template react-ts && cd axon-scaffold && pnpm install",
    "svelte":     "pnpm create svelte@latest axon-scaffold -- --template skeleton --types typescript --no-prettier --no-eslint && cd axon-scaffold && pnpm install",
    "astro":      "pnpm create astro@latest axon-scaffold -- --template minimal --typescript strict --git false --install --no-git",
    "vue":        "pnpm create vue@latest axon-scaffold -- --ts --router --pinia --no-eslint --no-prettier && cd axon-scaffold && pnpm install",
}

# Fichiers existants à ne jamais écraser lors du merge <transit>/ → project_dir
_SCAFFOLD_PRESERVE = {"spec.md", "readme.md", ".git", ".axon", "build-state.json"}


def _detect_framework(spec_text: str) -> Optional[str]:
    """Déduit le framework frontend depuis le texte de la spec. Retourne None si non identifiable."""
    text = spec_text.lower()
    if "next.js" in text or "nextjs" in text or "next js" in text or "create-next-app" in text:
        return "next"
    if "sveltekit" in text or "svelte kit" in text:
        return "svelte"
    if "astro" in text:
        return "astro"
    # Vue détecté seulement si Nuxt n'est pas mentionné (Nuxt = setup différent)
    if "vue" in text and "nuxt" not in text:
        return "vue"
    if "vite" in text or ("react" in text and "next" not in text):
        return "vite-react"
    return None


def _is_scaffold_phase(phase: Phase) -> bool:
    """Vérifie si une phase est un scaffold CLI exécutable avant le specialist."""
    if phase.index != 1:
        return False
    text = (phase.title + " " + phase.scope).lower()
    return any(kw in text for kw in (
        "scaffold", "setup", "init", "create next", "pnpm create",
        "npm create", "structure de dossier", "créer le projet", "stack",
    ))


def _merge_scaffold_into_project(scaffold_dir: Path, project_dir: Path) -> None:
    """Déplace les fichiers de scaffold_dir vers project_dir, en préservant les fichiers existants."""
    for item in scaffold_dir.iterdir():
        if item.name.lower() in _SCAFFOLD_PRESERVE:
            continue
        dest = project_dir / item.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(item), str(project_dir))
    shutil.rmtree(scaffold_dir, ignore_errors=True)


def _run_prescaffold(
    project_dir: Path,
    framework: str,
    console,
    accent: str,
) -> bool:
    """
    Exécute le scaffold CLI dans project_dir/<transit>/, puis merge dans project_dir.
    Retourne True si le scaffold a réussi, False sinon (le specialist prend la main).
    """
    from rich.text import Text

    cmd = _FRAMEWORK_SCAFFOLD_CMD.get(framework)
    if not cmd:
        return False

    scaffold_dir = project_dir / SCAFFOLD_DIRNAME

    # Ne pas re-scaffolder si un scaffold ou package.json existe déjà
    if (project_dir / "package.json").exists() or (project_dir / "node_modules").exists():
        t = Text()
        t.append("  ↺  ", style=f"bold {accent}")
        t.append("package.json déjà présent — scaffold ignoré", style="dim")
        console.print(t)
        return True

    t = Text()
    t.append("  ⚙  ", style=f"bold {accent}")
    t.append(f"pre-scaffold {framework} en cours…", style="dim")
    console.print(t)

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        t = Text()
        t.append("  ⚠  ", style="bold yellow")
        t.append("pre-scaffold timeout (5 min) — le specialist va le faire", style="dim yellow")
        console.print(t)
        return False

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-300:].strip()
        t = Text()
        t.append("  ⚠  ", style="bold yellow")
        t.append(f"pre-scaffold échoué (exit {proc.returncode}) — le specialist va le faire", style="dim yellow")
        console.print(t)
        if err:
            console.print(Text(f"      {err[:200]}", style="dim red"))
        return False

    # Scaffold réussi : merge du dossier de transit dans project_dir
    if scaffold_dir.exists():
        _merge_scaffold_into_project(scaffold_dir, project_dir)

    t = Text()
    t.append("  ✓  ", style="bold green")
    t.append(f"scaffold {framework} terminé — node_modules installés", style="dim")
    console.print(t)
    return True


def _find_spec(project_name: str) -> Optional[Path]:
    from src.utils.paths import get_projects_dir
    p = Path(project_name)
    if p.is_file():
        return p

    def _spec_in_dir(d: Path) -> Optional[Path]:
        """Find spec.md or any *spec*.md (case-insensitive) in directory."""
        exact = d / "spec.md"
        if exact.is_file():
            return exact
        try:
            matches = sorted(
                (f for f in d.iterdir() if f.is_file() and "spec" in f.name.lower() and f.suffix.lower() == ".md"),
                key=lambda f: f.name.lower(),
            )
        except PermissionError:
            matches = []
        return matches[0] if matches else None

    candidate = _spec_in_dir(get_projects_dir() / project_name)
    if candidate:
        return candidate
    for d in get_projects_dir().iterdir():
        if d.is_dir() and project_name.lower() in d.name.lower():
            c = _spec_in_dir(d)
            if c:
                return c
    return None


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _state_path(project_dir: Path) -> Path:
    return project_dir / ".axon" / "build-state.json"


def _load_state(project_dir: Path) -> Optional[dict]:
    p = _state_path(project_dir)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_state(project_dir: Path, state: dict) -> None:
    _atomic_write_json(_state_path(project_dir), state)


def _load_axon_context(project_dir: Path) -> str:
    """Lit .axon/memory/ (journal + décisions) pour enrichir le contexte inter-phases."""
    parts = []
    mdir = project_dir / ".axon" / "memory"
    if not mdir.exists():
        return ""
    journal = mdir / "journal.md"
    if journal.is_file():
        content = journal.read_text(encoding="utf-8")
        entries = content.split("\n## ")
        if len(entries) > 1:
            last = "## " + entries[1]  # prepend order → entries[1] is newest
            parts.append(f"Dernière session (journal) :\n{last[:1500]}")
    decisions = mdir / "decisions.md"
    if decisions.is_file():
        content = decisions.read_text(encoding="utf-8")
        blocks = content.split("\n## ")
        recent = [b for b in blocks[1:3] if b.strip()]
        if recent:
            parts.append("Décisions récentes :\n" + "\n---\n".join(f"## {b}" for b in recent)[:1500])
    return "\n\n".join(parts)


def _compress_spec_for_phase(spec_text: str, phases: list[Phase], current: Phase,
                             echouees: set[int] | None = None) -> str:
    """Phase 1 reçoit la spec complète. Phases suivantes : intro + liste compacte.

    UNE PHASE ANTÉRIEURE ÉCHOUÉE EST DITE ÉCHOUÉE. Le statut se déduisait du
    seul numéro — « ✓ faite » pour tout ce qui précède — si bien qu'une phase
    morte deux fois était annoncée comme livrée à la suivante. Mesuré sur un vrai
    build : la phase 4 « Polish & finalisation » a vérifié et validé une page que
    la phase 3 n'avait jamais écrite, et le build s'est terminé sur un squelette
    annoncé comme fini.

    Le travail manquant est alors nommé : la phase suivante peut le signaler, ou
    le reprendre si son scope le permet, au lieu de polir du vide.
    """
    if current.index == 1:
        return spec_text[:6000]
    echouees = echouees or set()
    intro = spec_text[:500]

    def _statut(p: Phase) -> str:
        if p.index in echouees:
            return "✗ ÉCHOUÉE — son travail N'EXISTE PAS"
        return "✓ faite" if p.index < current.index else "à venir"

    others = "\n".join(
        f"  Phase {p.index} ({p.title}) : {_statut(p)}"
        for p in phases if p.index != current.index
    )
    bloc = f"{intro}\n\nAutres phases :\n{others}"
    manquantes = sorted(i for i in echouees if i < current.index)
    if manquantes:
        bloc += (
            f"\n\n⚠ Les phases {manquantes} ont ÉCHOUÉ : leurs livrables sont "
            "absents. Ne les considère jamais comme présents, et ne valide pas "
            "un résultat qui en dépend."
        )
    return bloc


_EXPORT = __import__("re").compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:function|const|class|interface|type)\s+([A-Za-z_$][\w$]*)", __import__("re").M)

_IGNORES = {"node_modules", ".next", ".git", "dist", "build", ".axon", "__pycache__"}
_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".svelte", ".vue", ".py", ".css"}


def _inventaire_du_projet(project_dir: Path, max_fichiers: int = 60) -> str:
    """Ce qui existe déjà, avec ce que chaque fichier EXPORTE.

    C'est la correction du vrai coût du build. Une phase recevait son scope mais
    aucune idée de ce que les phases précédentes avaient produit : pour écrire
    une page composant Header, Button et Container, l'agent devait d'abord lire
    ces fichiers un par un. Mesuré sur un vrai build : sept à douze `read_file`
    par phase, avant la moindre écriture — et le détecteur de boucle y voyait une
    répétition.

    Lister les exports coûte quelques centaines de tokens et remplace la
    quasi-totalité de ces lectures : l'agent sait que `Button.tsx` exporte
    `Button` et `LinkButton` sans avoir à l'ouvrir. Il garde le droit de lire,
    mais n'en a plus BESOIN pour connaître la surface du projet.
    """
    if not project_dir.is_dir():
        return ""
    lignes: list[str] = []
    for chemin in sorted(project_dir.rglob("*")):
        if len(lignes) >= max_fichiers:
            lignes.append("  … (inventaire tronqué)")
            break
        if not chemin.is_file() or chemin.suffix not in _EXTENSIONS:
            continue
        if any(part in _IGNORES for part in chemin.parts):
            continue
        relatif = chemin.relative_to(project_dir)
        try:
            contenu = chemin.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        exports = _EXPORT.findall(contenu)
        n = len(contenu.splitlines())
        detail = f" → {', '.join(dict.fromkeys(exports))}" if exports else ""
        lignes.append(f"  {relatif} ({n} l.){detail}")
    return "\n".join(lignes)


def _capacites_mcp() -> str:
    """Les serveurs MCP connectés, annoncés à la phase.

    Brancher les outils ne suffit pas. Le specialist ne lie que les huit outils
    les plus proches de sa requête : si la tâche ne parle jamais de 3D, les
    outils Blender ne sont jamais sélectionnés — présents, joignables, et
    invisibles. Les nommer dans la tâche fait deux choses à la fois : le modèle
    SAIT qu'il les a, et le texte rapproche la requête de leur description.

    Le `capabilities_hint` de la config sert de description : c'est déjà ce qui
    route les outils côté MCP, et le dupliquer autrement les ferait diverger.
    """
    try:
        from src.mcp_client.runtime import mcp_runtime
        runtime = mcp_runtime()
        outils = {t.name for t in runtime.tools}
        lignes = []
        for nom, cfg in runtime.servers().items():
            if not getattr(cfg, "enabled", True):
                continue
            hint = (getattr(cfg, "capabilities_hint", "") or "").strip()
            lignes.append(f"  · {nom} — {hint or 'capacités non décrites'}")
    except Exception:                                            # noqa: BLE001
        return ""
    if not lignes:
        return ""
    return (
        "OUTILS MCP CONNECTÉS (utilisables directement, comme tes autres outils) :\n"
        + "\n".join(lignes)
        + f"\n  ({len(outils)} outils exposés au total)\n"
        "Si le scope de la phase relève d'une de ces capacités, PASSE PAR L'OUTIL "
        "plutôt que d'écrire du code qui la réimplémente.\n\n"
    )


def _build_phase_task(phase: Phase, spec_text: str, project_name: str,
                      project_dir: Path, phases: list[Phase],
                      echec_precedent: str = "",
                      echouees: set[int] | None = None) -> str:
    axon_ctx = _load_axon_context(project_dir)
    spec_part = _compress_spec_for_phase(spec_text, phases, phase, echouees)
    inventaire = _inventaire_du_projet(project_dir)
    task = (
        f"[Phase {phase.index}/{len(phases)} — {phase.title}]\n"
        f"Projet : {project_name}\n\n"
        f"SCOPE DE CETTE PHASE (et uniquement ça) :\n{phase.scope}\n\n"
        f"RÈGLE ABSOLUE : Si une tâche n'est PAS dans le scope ci-dessus, ignore-la "
        f"même si tu sais la faire. Ne jamais anticiper sur les phases suivantes.\n\n"
        f"SPEC (référence) :\n{spec_part}\n\n"
    )
    if inventaire:
        task += (
            "FICHIERS DÉJÀ PRÉSENTS (avec leurs exports) :\n"
            f"{inventaire}\n\n"
            "Cet inventaire est À JOUR : tu connais déjà la surface du projet. "
            "N'ouvre un fichier que si tu as besoin de son CONTENU — pas pour "
            "savoir s'il existe ni ce qu'il exporte.\n\n"
        )
    task += _capacites_mcp()
    if axon_ctx:
        task += f"CONTEXTE PROJET (sessions précédentes) :\n{axon_ctx}\n\n"
    if echec_precedent:
        # Un retry qui renvoie la tâche identique reproduit l'échec identique.
        # Mesuré : phase 3 morte deux fois de suite sur la même exploration.
        task += (
            "⚠ TENTATIVE PRÉCÉDENTE ÉCHOUÉE\n"
            f"Motif : {echec_precedent}\n"
            "Ne recommence pas la même approche. Tu as l'inventaire ci-dessus : "
            "commence par ÉCRIRE un fichier du scope, puis lis seulement ce qui "
            "te manque ensuite.\n\n"
        )
    task += (
        "Instructions :\n"
        "- Réalise UNIQUEMENT le scope défini ci-dessus.\n"
        "- Les phases précédentes ont déjà été exécutées — ne pas re-scaffolder.\n"
        "- ÉCRIS TÔT. Une phase qui n'a produit aucun fichier n'a rien livré : "
        "l'exploration ne compte pas comme du travail.\n"
        "- Plan COURT obligatoire : dev_plan avec 4 à 6 steps max. Chaque step = une action atomique.\n"
        "  Exemple de bons steps : 'Scaffolder avec create-next-app', 'Installer les dépendances',\n"
        "  'Configurer tailwind.config.js + globals.css', 'Créer la structure de dossiers'.\n"
        "  Les fichiers proposés via propose_file_change comptent comme une seule action par step.\n"
        "- En fin de phase : appelle OBLIGATOIREMENT axon_note() pour noter :\n"
        "  les fichiers créés/modifiés (chemins exacts), les technologies et versions choisies,\n"
        "  les problèmes rencontrés et comment ils ont été résolus.\n"
        "  Cette note est ESSENTIELLE pour que les phases suivantes aient le bon contexte."
    )
    return task


def _phase_failed(result: str) -> bool:
    lower = result.lower()
    return any(marker in lower for marker in _PHASE_FAILED_MARKERS)


_LOOP_DETECTION_LIMIT = 8   # même appel IDENTIQUE répété N fois → boucle
_WRITE_EVENTS = ("propose_file_change", "edit_file")

#: Lectures distinctes tolérées avant d'exiger une écriture. Explorer n'est pas
#: boucler — mais explorer indéfiniment non plus.
_EXPLORATION_MAX = 14


def _cible_de(event: str, data: dict) -> str:
    """Ce sur QUOI porte l'appel — chemin, motif ou commande.

    C'est la correction du défaut central du détecteur : il comptait les appels
    par NOM D'OUTIL. Lire sept fichiers DIFFÉRENTS avant d'écrire une page qui
    les compose était donc traité comme une boucle, et la phase tuée.
    Mesuré sur un vrai build : les phases 3 et 4 sont mortes ainsi, deux fois
    chacune, et le site est resté un squelette.

    Lire sept fois le MÊME fichier reste une boucle. La différence tient
    entièrement à l'argument, jamais au nom de l'outil.
    """
    for cle in ("path", "file_path", "name", "pattern", "query", "cmd", "command"):
        valeur = data.get(cle)
        if valeur:
            return f"{event}:{str(valeur)[:120]}"
    return event

def _make_build_callback(console, accent: str = "color(214)"):
    """Factory : retourne un callback /build avec visibilité et détection de boucle."""
    from collections import Counter
    from rich.text import Text

    _recent_tools: list[str] = []   # outil invocations depuis le dernier fichier écrit
    _files_written: list[str] = []
    _aborted = [False]   # flag closure pour éviter de re-déclencher abort

    # shell_run:stream = lignes stdout d'une commande en cours — jamais compté comme répétition
    _LOOP_IGNORED = {"shell_run:stream", "shell_run:before", "shell_cd:before",
                     "shell_run", "specialist:thinking", "specialist:response",
                     "specialist:start", "specialist:done", "specialist:compress"}

    # shell_run:before is called with 2 args (no result), all others with 3
    def _cb(event: str, data: dict, result=None) -> object:
        nonlocal _recent_tools
        if data is None:
            data = {}

        # ── Visibilité ────────────────────────────────────────────────────────
        if event == "shell_run:before":
            # data = args dict with cmd/command key
            cmd = (data.get("cmd") or data.get("command") or "")[:80]
            t = Text()
            t.append("    $  ", style=f"dim {accent}")
            t.append(cmd, style="dim")
            console.print(t)
            _recent_tools.append(_cible_de("shell_run", data))  # UNE entrée par invocation

        elif event == "shell_run":
            # data = args, result = {"exit_code": N, "stdout": ..., "stderr": ...}
            res = result if isinstance(result, dict) else {}
            code = res.get("exit_code", "?")
            style = "dim green" if code == 0 else "dim red"
            t = Text()
            t.append(f"    └  exit {code}", style=style)
            if code != 0:
                err = (res.get("stderr") or res.get("stdout") or "")[:120].strip()
                if err:
                    t.append(f"  {err}", style="dim red")
            console.print(t)

        elif event == "dev_plan_create":
            steps = data.get("steps", [])
            t = Text()
            t.append("  ◆  plan : ", style=f"bold {accent}")
            t.append(", ".join(steps[:4]) + ("…" if len(steps) > 4 else ""), style="dim")
            console.print(t)
            _recent_tools.append(_cible_de("dev_plan_create", data))

        elif event == "dev_plan_step_done":
            res = result if isinstance(result, dict) else {}
            step = res.get("step") or data.get("step") or ""
            t = Text()
            t.append("  ✓  ", style="bold green")
            t.append(step[:80], style="dim")
            console.print(t)

        elif event == "dev_explain":
            msg = (data.get("message") or "")[:120]
            t = Text()
            t.append("  ℹ  ", style=f"dim {accent}")
            t.append(msg, style="dim")
            console.print(t)

        elif event == "specialist:backend_switch":
            from_p = data.get("from", "?")
            to_p   = data.get("to", "?")
            key    = data.get("key", "")
            _recent_tools.clear()  # reset loop detection — nouveau modèle repart de zéro
            _aborted[0] = False
            t = Text()
            t.append("  ↻  backend switch ", style=f"bold {accent}")
            t.append(f"{from_p} → {to_p}", style="bold white")
            if key:
                t.append(f"  ({key})", style="dim")
            console.print(t)

        elif event in ("local_read_file", "local_find_file", "local_grep"):
            path = (data.get("path") or data.get("name") or data.get("pattern") or "")[:60]
            t = Text()
            t.append(f"  ∙  {event.split('_', 1)[1]}  ", style="dim")
            t.append(path, style="dim")
            console.print(t)
            _recent_tools.append(_cible_de(event, data))

        elif event not in _WRITE_EVENTS and event not in _LOOP_IGNORED:
            _recent_tools.append(_cible_de(event, data))

        # ── Auto-accept des écritures ─────────────────────────────────────────
        if event not in _WRITE_EVENTS:
            # Détection de boucle : même outil LLM trop répété sans fichier écrit
            if not _aborted[0] and len(_recent_tools) >= _LOOP_DETECTION_LIMIT:
                counts = Counter(_recent_tools[-_LOOP_DETECTION_LIMIT:])
                dominant = counts.most_common(1)
                if dominant and dominant[0][1] >= _LOOP_DETECTION_LIMIT - 1:
                    top_tool = dominant[0][0]
                    t = Text()
                    t.append("  ⚠  boucle détectée ", style="bold yellow")
                    t.append(f"({top_tool} × {dominant[0][1]}, 0 fichier écrit) — phase abandonnée", style="dim yellow")
                    console.print(t)
                    _aborted[0] = True
                    from src.agents.coding.specialist import _abort_phase
                    _abort_phase()
            return None

        # Un appel en erreur n'a rien déposé : dépiler écrirait la proposition
        # précédente sous le chemin d'une autre.
        if isinstance(result, dict) and result.get("status") == "error":
            return None

        # Le contenu vient de la pile, jamais des arguments : `edit_file` ne passe
        # qu'un fragment, et c'est l'outil qui a calculé le fichier complet.
        from src.agents.coding.pending import pending_changes as _pending, snapshots as _snaps
        change = _pending.pop_latest()
        if change is None:
            return None
        path, desc = change.path, (data.get("description") or change.description)[:60]

        try:
            from pathlib import Path as _Path
            p = _Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            _snaps.save(path, change.original)
            p.write_text(change.proposed, encoding="utf-8")
            _files_written.append(path)
            _recent_tools.clear()  # reset loop counter après un vrai fichier
            t = Text()
            t.append("  ✎  ", style=f"bold {accent}")
            t.append(f"{p.name}", style=f"{accent}")
            if desc:
                t.append(f"  {desc}", style="dim")
            console.print(t)
            return {
                "status": "accepted",
                "path": path,
                "awaiting_confirmation": False,
                "auto_accepted": True,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "awaiting_confirmation": False}

    return _cb


def run_build(project_name: str, console) -> None:
    from rich.text import Text
    from rich.rule import Rule
    from src.infra.settings import settings
    from src.agents.coding.specialist import run_coding_task, set_phase_max_iterations, set_progress_callback
    from src.agents.coding.pending import reset_specialist_state
    from src.ui.panels import command_panel

    ACCENT = "color(214)"

    spec_path = _find_spec(project_name)
    if spec_path is None:
        console.print(command_panel(
            f"spec.md introuvable pour '{project_name}' — lance d'abord /spec {project_name}",
            error=True
        ))
        return

    spec_text = spec_path.read_text(encoding="utf-8")
    project_dir = spec_path.parent

    console.print()
    console.print(Rule(f"build · {project_name}", characters="·", style=f"dim {ACCENT}"))

    # Vérifier si reprise possible
    existing_state = _load_state(project_dir)
    resume_from = 1
    if existing_state and existing_state.get("project") == project_name:
        completed = existing_state.get("completed", [])
        total = existing_state.get("total", 0)
        if completed and len(completed) < total:
            resume_from = max(completed) + 1
            t = Text()
            t.append("  ↺  ", style=f"bold {ACCENT}")
            t.append(f"reprise depuis la phase {resume_from} (complétées : {completed})", style="dim")
            console.print(t)

    # Décomposer (ou réutiliser plan existant)
    if existing_state and existing_state.get("phases_plan") and existing_state.get("project") == project_name:
        raw = existing_state["phases_plan"]
        phases = [Phase(index=p["index"], title=p["title"], scope=p["scope"]) for p in raw]
        console.print(Text("  ↺  plan de phases rechargé depuis build-state.json", style=f"dim {ACCENT}"))
    else:
        t = Text()
        t.append("  ⚙  ", style=f"bold {ACCENT}")
        t.append("décomposition de la spec en phases…", style="dim")
        console.print(t)
        phases = decompose(spec_text, settings.llm_backend)

    for ph in phases:
        done = ph.index < resume_from
        t = Text()
        t.append(f"  {'✓' if done else str(ph.index)}. ", style=f"bold {'green' if done else ACCENT}")
        t.append(ph.title, style="dim" if done else "white")
        console.print(t)
    console.print()

    phase_iter_budget = _PHASE_ITER_BUDGET.get(settings.llm_backend, 60)

    build_state = {
        "project": project_name,
        "spec_path": str(spec_path),
        "total": len(phases),
        "completed": list(range(1, resume_from)),
        "failed": [],
        "last_run": datetime.now().isoformat(),
        "backend": settings.llm_backend,
        "phases_plan": [{"index": p.index, "title": p.title, "scope": p.scope} for p in phases],
    }
    _save_state(project_dir, build_state)

    # Détection du framework une seule fois pour toutes les phases
    detected_framework = _detect_framework(spec_text)

    for phase in phases:
        if phase.index < resume_from:
            continue

        console.print(Rule(
            f"phase {phase.index}/{len(phases)} · {phase.title}",
            characters="─", style=f"dim {ACCENT}"
        ))

        # Pre-scaffold : exécute pnpm create ... en subprocess avant de passer au specialist
        prescaffold_done = False
        if detected_framework and _is_scaffold_phase(phase):
            prescaffold_done = _run_prescaffold(project_dir, detected_framework, console, ACCENT)

        # La tâche est reconstruite à CHAQUE tentative : l'inventaire a pu
        # changer (la tentative précédente a peut-être écrit), et le motif
        # d'échec doit y entrer.
        motif_echec = ""

        if prescaffold_done:
            task = (
                "[PRÉ-SCAFFOLD EFFECTUÉ AUTOMATIQUEMENT]\n"
                f"Framework : {detected_framework} · pnpm create a déjà tourné avec succès.\n"
                "package.json, node_modules, tsconfig, structure src/ sont en place.\n"
                "⚠ NE PAS relancer pnpm create next-app ou équivalent — scaffold déjà fait.\n"
                "Continue directement avec : tailwind.config.ts, globals.css, "
                "structure de dossiers spécifique au projet, composants partagés.\n\n"
                + task
            )

        success = False
        result = ""
        for attempt in range(2):
            # Isolation : reset singletons + budget + callback frais (reset loop detector)
            reset_specialist_state()
            set_phase_max_iterations(phase_iter_budget)
            set_progress_callback(_make_build_callback(console, ACCENT))
            task = _build_phase_task(phase, spec_text, project_name, project_dir,
                                     phases, echec_precedent=motif_echec,
                                     echouees=set(build_state["failed"]))
            try:
                result = run_coding_task(task)
                if _phase_failed(result):
                    raise RuntimeError(result[:120])
                success = True
                break
            except Exception as exc:
                motif_echec = str(exc)[:200]
                if attempt == 0:
                    t = Text()
                    t.append("  ⚠  ", style="bold yellow")
                    t.append(f"phase {phase.index} échouée, retry… ({str(exc)[:80]})", style="dim yellow")
                    console.print(t)

        set_phase_max_iterations(None)

        if success:
            build_state["completed"].append(phase.index)
            summary = " ".join(
                l for l in result.splitlines()
                if l.strip()
                   and not l.startswith("[SPECIALIST") and not l.startswith("[/SPECIALIST")
                   and not l.startswith("cwd:") and not l.startswith("files:") and not l.startswith("plan:")
            )
            if summary:
                console.print(Text("  " + summary[:140], style="dim"))
        else:
            build_state["failed"].append(phase.index)
            t = Text()
            t.append("  ✗  ", style="bold red")
            t.append(f"phase {phase.index} échouée après retry — build continue", style="dim red")
            console.print(t)

        build_state["last_run"] = datetime.now().isoformat()
        _save_state(project_dir, build_state)
        console.print()

    failed = build_state["failed"]
    console.print(Rule("build terminé", characters="·", style=f"dim {ACCENT}"))
    t = Text()
    if not failed:
        t.append("  ✓  ", style=f"bold {ACCENT}")
        t.append(f"{len(phases)} phases · spec : ", style="dim")
        t.append(str(spec_path), style=ACCENT)
    else:
        t.append("  ⚠  ", style="bold yellow")
        t.append(
            f"terminé avec échecs phases {failed} · relance /build {project_name} pour reprendre",
            style="dim"
        )
    console.print(t)

    # Restore : plus de callback auto-accept après le build
    set_progress_callback(None)
