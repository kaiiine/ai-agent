"""Coding specialist — runs qwen3-coder-next:cloud for coding tasks delegated by the orchestrator."""
from __future__ import annotations

import json
from typing import Callable, Optional

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

# Module-level progress callback set by the streaming UI
_progress_cb: Optional[Callable[[str, dict], None]] = None


def set_progress_callback(cb: Optional[Callable[[str, dict], None]]) -> None:
    global _progress_cb
    _progress_cb = cb


def _get_coding_llm():
    from src.llm.models import make_coding_llm
    return make_coding_llm()


def _get_coding_tools():
    from src.agents.coding.tools import (
        dev_plan_create, dev_plan_step_done, dev_explain, find_git_repos, propose_file_change,  # noqa: F401
    )
    from src.agents.filesystem.tools import (
        local_find_file, local_read_file, local_list_directory,
        local_grep, local_glob,
    )
    from src.agents.shell.tools import shell_run, shell_cd, shell_pwd, shell_ls
    from src.agents.git.tools import (
        git_status, git_log, git_diff, git_suggest_commit,
        git_add, git_commit, git_checkout, git_stash,
        url_fetch,
    )
    return [
        dev_plan_create, dev_plan_step_done, dev_explain,
        find_git_repos, propose_file_change,
        local_find_file, local_read_file, local_list_directory,
        local_grep, local_glob,
        shell_run, shell_cd, shell_pwd, shell_ls,
        git_status, git_log, git_diff, git_suggest_commit,
        git_add, git_commit, git_checkout, git_stash,
        url_fetch,
    ]


_CODING_SYSTEM_PROMPT = """\
Tu es un agent de code expert. Tu reçois une tâche précise de l'orchestrateur et tu l'exécutes.
Réponds en français. Exécute sans demander de confirmation supplémentaire.

⚠ RÈGLE ABSOLUE : dev_plan_create() doit être TON PREMIER appel, avant tout autre outil.

Workflow strict :
1. dev_plan_create(steps=[...]) — plan de 3 à 8 étapes concrètes. Toujours en premier.
2. find_git_repos / local_read_file / shell_run — pour analyser le projet.
3. dev_explain(message=...) — OBLIGATOIRE après analyse, avant toute modification.
   Explique en markdown : ce que tu as trouvé, les bugs et leur cause, ce que tu vas changer et pourquoi.
4. dev_plan_step_done(N) — immédiatement après chaque étape terminée.
5. propose_file_change(path, content, description) — pour chaque fichier à modifier/créer.
   L'utilisateur peut approuver, refuser ou demander des modifications :
   - status "proposed"           → accepté, continue
   - status "rejected"           → ignoré, passe au fichier suivant
   - status "needs_refinement"   → lis le champ "feedback" et rappelle propose_file_change
                                   avec le contenu corrigé. Ne passe pas au fichier suivant.
6. Vérification automatique après toutes les modifications (max 3 cycles) :
   a. Lance la commande de vérification adaptée au projet :
      - Next.js/React : `npm run build` ou `npx tsc --noEmit`
      - Python : `python -m py_compile fichier.py` ou `pytest`
      - Autre : adapte selon le contexte
   b. Si erreur détectée :
      - dev_explain("🔍 Problème détecté dans `fichier` : <erreur>.\n\nCause : <explication>.\n\nCorrection : je remplace `X` par `Y` parce que <raison>.")
      - propose_file_change(...) pour corriger
      - Relance la vérification
   c. Si tout est propre :
      - dev_explain("✅ Vérification OK — aucune erreur détectée.")
7. Retourne un résumé concis (2-3 lignes) de ce qui a été fait.

Pour modifier ou créer un fichier : UNIQUEMENT propose_file_change. Jamais shell_run ou redirection.
"""

_PROGRESS_TOOLS = {"dev_plan_create", "dev_plan_step_done", "dev_explain", "propose_file_change"}
_MAX_ITERATIONS = 150


def run_coding_task(task: str) -> str:
    """
    Runs a coding task using the specialized coding LLM.
    Calls the global progress callback on plan/file events so the UI can update in real time.
    Returns a summary string.
    """
    llm = _get_coding_llm()
    tools = _get_coding_tools()
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    messages = [SystemMessage(_CODING_SYSTEM_PROMPT), HumanMessage(task)]

    for _ in range(_MAX_ITERATIONS):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return response.content or "Tâche terminée."

        for tc in response.tool_calls:
            name = tc["name"]
            args = tc.get("args", {})

            # Execute the tool
            tool_fn = tool_map.get(name)
            if tool_fn:
                try:
                    result = tool_fn.invoke(args)
                except Exception as e:
                    result = {"status": "error", "error": str(e)}
            else:
                result = {"status": "error", "error": f"Outil inconnu : {name}"}

            # Notify UI — skip if step was already done (no change)
            # _progress_cb may return a dict to override the ToolMessage content
            # (used for HITL review on propose_file_change)
            if _progress_cb and name in _PROGRESS_TOOLS:
                skip = (name == "dev_plan_step_done" and
                        isinstance(result, dict) and
                        result.get("status") == "already_done")
                if not skip:
                    try:
                        override = _progress_cb(name, args)
                        if isinstance(override, dict):
                            result = override
                    except Exception:
                        pass

            messages.append(ToolMessage(
                content=json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
                tool_call_id=tc["id"],
                name=name,
            ))

    return "Tâche interrompue (limite d'itérations atteinte)."
