"""Coding agent tools — repo discovery, HITL file proposals, dev plan."""
from __future__ import annotations

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


@tool("browser_screenshot")
def browser_screenshot(
    url: str,
    width: int = 1280,
    height: int = 900,
    wait_ms: int = 2500,
) -> dict:
    """
    Takes a headless screenshot of a running web application and returns its rendered page text.
    Use this after starting the dev server to verify the UI visually matches expectations.

    Workflow :
      1. shell_run("npm run dev &") — lance le serveur en arrière-plan
      2. shell_run("sleep 4")       — attends que le serveur soit prêt
      3. browser_screenshot("http://localhost:3000") — capture + texte DOM
      4. Analyse le texte retourné et corrige si nécessaire

    Args:
        url:      URL à capturer, ex. "http://localhost:3000"
        width:    largeur du viewport en pixels (défaut 1280)
        height:   hauteur du viewport en pixels (défaut 900)
        wait_ms:  temps d'attente JS virtuel en ms (défaut 2500)
    Returns:
        {"status": "ok", "screenshot_path": str, "page_text": str, "url": str,
         "audit": {"title": str, "h1s": list, "issueCount": int, "issues": list}}
        {"status": "error", "error": str}
    """
    from src.infra.browser import screenshot_url
    return screenshot_url(url, width=width, height=height, wait_ms=wait_ms)


@tool("load_skill")
def load_skill(stack: str) -> str:
    """
    Loads best-practice guidelines for a detected tech stack.
    Call this as soon as you identify the framework/language used in the project.
    Returns a detailed prompt with rules, conventions, and tooling for that stack.

    Available stacks: nextjs, angular, vue, svelte, threedee, python,
                      rust, go, node_backend, java, systems, frontend

    Args:
        stack: detected stack name (e.g. "nextjs", "python", "vue")
    Returns:
        Full guidelines prompt for that stack
    """
    from src.agents.coding.skill_retriever import get_skill, list_skills
    result = get_skill(stack)
    if not result or result.startswith("Skill '"):
        from src.agents.coding.prompts import _STACK_PROMPTS
        result = _STACK_PROMPTS.get(stack.lower(), f"Stack '{stack}' non reconnu. Disponibles : {', '.join(list_skills())}")
    return result


@tool("propose_file_change")
def propose_file_change(path: str, content: str, description: str) -> Dict[str, Any]:
    """
    Proposes creating or modifying a file WITHOUT writing to disk.
    The user will be shown a diff and asked to approve, reject, or refine.
    ALWAYS use this instead of shell_run or any direct write when modifying a user's project.
    Call it once per file. Multiple calls accumulate — all shown together before validation.

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
