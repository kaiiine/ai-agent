"""Coding agent tools — repo discovery, HITL file proposals, dev plan."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Any, List

from langchain_core.tools import tool

from src.agents.coding.pending import FileChange, pending_changes, dev_plan

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


@tool("dev_plan_step_done")
def dev_plan_step_done(step_index: int) -> Dict[str, Any]:
    """
    Marks a plan step as completed and refreshes the plan display.
    Call this immediately after finishing each step.

    Args:
        step_index: zero-based index of the completed step
    Returns:
        {"status": "ok", "step": label} or {"status": "error"}
    """
    steps = dev_plan.steps
    if not (0 <= step_index < len(steps)):
        return {"status": "error", "error": f"Index {step_index} hors limites (plan : {len(steps)} étapes)"}

    changed = dev_plan.check(step_index)
    label = steps[step_index].label
    if not changed:
        return {"status": "already_done", "step": label}
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
    # The actual display is handled by the UI via the progress callback
    return {"status": "ok", "message": message}


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
