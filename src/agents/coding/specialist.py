"""Coding specialist — runs qwen3-coder-next:cloud for coding tasks delegated by the orchestrator."""
from __future__ import annotations

import json
import re as _re
import uuid
from typing import Callable, Optional

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage
from src.agents.coding.prompts import build_system_prompt
from src.agents.coding.prompts.detector import detect_stacks

# Module-level progress callback set by the streaming UI
_progress_cb: Optional[Callable[[str, dict, Optional[dict]], Optional[dict]]] = None


def set_progress_callback(cb: Optional[Callable[[str, dict, Optional[dict]], Optional[dict]]]) -> None:
    global _progress_cb
    _progress_cb = cb


def _get_coding_llm():
    from src.llm.models import make_coding_llm
    return make_coding_llm()


def _get_coding_tools():
    from src.agents.coding.tools import (
        dev_plan_create, dev_plan_step_done, dev_explain, find_git_repos,
        propose_file_change, browser_screenshot,  # noqa: F401
    )
    from src.agents.filesystem.tools import (
        local_find_file, local_read_file, local_list_directory,
        local_grep, local_glob,
    )
    from src.agents.shell.tools import shell_run, shell_cd, shell_pwd, shell_ls, shell_kill_bg
    from src.agents.git.tools import (
        git_status, git_log, git_diff, git_suggest_commit,
        git_add, git_commit, git_checkout, git_stash,
        url_fetch,
    )
    from src.agents.memory.tools import axon_note
    from src.agents.search.tools import web_research_report, web_search_news
    from src.agents.excalidraw.tools import excalidraw_create
    from src.agents.coding.asset_downloader import download_asset
    return [
        dev_plan_create, dev_plan_step_done, dev_explain,
        find_git_repos, propose_file_change, browser_screenshot,
        local_find_file, local_read_file, local_list_directory,
        local_grep, local_glob,
        shell_run, shell_cd, shell_pwd, shell_ls, shell_kill_bg,
        git_status, git_log, git_diff, git_suggest_commit,
        git_add, git_commit, git_checkout, git_stash,
        url_fetch,
        axon_note,
        web_research_report, web_search_news,
        excalidraw_create,
        download_asset,
    ]


_PROGRESS_TOOLS = {
    "dev_plan_create", "dev_plan_step_done", "dev_explain", "propose_file_change", "axon_note",
    "local_read_file", "local_grep", "local_glob", "local_find_file", "local_list_directory",
    "shell_ls", "shell_pwd", "url_fetch", "web_research_report", "web_search_news",
    "git_status", "git_log", "git_diff",
}
_SHELL_PREVIEW_TOOLS = {"shell_run", "shell_cd"}
_MAX_ITERATIONS = 75
_CONTEXT_CHAR_BUDGET = 150_000  # ~50k tokens — conservative to leave room for tool descriptions


def _compress_specialist_messages(messages: list, llm) -> list:
    """LLM-based context compression for the specialist — same philosophy as the orchestrator's
    'compiling' mechanism: produce a dense technical summary instead of truncating."""

    # Notify UI → switch to compile animation
    if _progress_cb:
        try:
            _progress_cb("specialist:compress", {}, None)
        except Exception:
            pass

    system_msg = messages[0]   # SystemMessage (specialist prompt)
    task_msg   = messages[1]   # HumanMessage  (original task)
    history    = messages[2:]  # everything accumulated so far

    transcript_parts: list[str] = []
    for m in history:
        if isinstance(m, AIMessage):
            if isinstance(m.content, str) and m.content.strip():
                transcript_parts.append(f"[ASSISTANT]: {m.content[:3_000]}")
            for tc in getattr(m, "tool_calls", []) or []:
                args_str = str(tc.get("args", {}))[:800]
                transcript_parts.append(f"[TOOL CALL] {tc.get('name')}({args_str})")
        elif isinstance(m, ToolMessage):
            name = getattr(m, "name", "tool") or "tool"
            content = m.content if isinstance(m.content, str) else str(m.content)
            transcript_parts.append(f"[TOOL RESULT] {name}: {content[:2_500]}")

    transcript = "\n".join(transcript_parts)
    # Cap transcript so the compression call itself never exceeds model limits
    if len(transcript) > 180_000:
        transcript = "…[début omis pour cause de longueur]\n" + transcript[-180_000:]

    prompt = (
        "Tu es un assistant de mémoire pour un agent de code actif.\n"
        "Voici la transcription COMPLÈTE des actions effectuées jusqu'ici par l'agent.\n\n"
        "Génère un résumé DENSE et TECHNIQUE qui lui permettra de continuer sans perte d'information.\n"
        "Préserve ABSOLUMENT :\n"
        "1. Le plan — étapes complétées ✓ et restantes ○ avec leurs indices\n"
        "2. Chaque fichier lu, modifié ou créé — chemin EXACT + contenu ou diff clé\n"
        "3. Le répertoire de travail courant (dernier shell_cd)\n"
        "4. Commandes exécutées et leur résultat (succès / erreur + cause)\n"
        "5. Dépendances installées, variables d'env, configs importantes\n"
        "6. Ce qui était exactement en cours au moment de la compression\n\n"
        f"TRANSCRIPTION :\n{transcript}\n\n"
        "Résumé dense (chemins exacts, noms de variables, valeurs de config — pas de généralités) :"
    )

    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        summary_content = resp.content
        if isinstance(summary_content, list):
            summary_content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in summary_content
            )
        summary_msg = HumanMessage(
            content=f"[CONTEXTE COMPRESSÉ — continue la tâche]\n{summary_content}"
        )
        return [system_msg, task_msg, summary_msg]
    except Exception:
        # Fallback: keep only the last 10 messages (best-effort, never truncate content)
        return [system_msg, task_msg] + history[-10:]


def _vram_swap_in() -> None:
    """On local ollama: unload the main agentic model to free VRAM for the coding specialist."""
    from src.infra.settings import settings
    if settings.llm_backend != "ollama":
        return
    from src.llm.models import _ollama_unload
    _ollama_unload(settings.ollama_model)


def _vram_swap_out() -> None:
    """On local ollama: unload the coding model so the main model can reload on next use."""
    from src.infra.settings import settings
    if settings.llm_backend != "ollama":
        return
    from src.llm.models import _ollama_unload
    _ollama_unload(settings.coding_model_local)


def run_coding_task(task: str) -> str:
    """
    Runs a coding task using the specialized coding LLM.
    Calls the global progress callback on plan/file events so the UI can update in real time.
    Returns a summary string.
    """
    _vram_swap_in()
    try:
        return _run(task)
    finally:
        _vram_swap_out()


_MSG_REPR_RE = _re.compile(
    r'\[?\s*(?:Human|System|AI|Tool)Message\s*\(.*?\)\s*\]?',
    _re.DOTALL,
)


def _clean_output(content: str) -> str:
    """Remove Python LangChain message repr blocks from model output."""
    # Remove entire [...Message(...)] blocks wherever they appear
    cleaned = _MSG_REPR_RE.sub('', content)
    # Collapse excessive blank lines left by removal
    cleaned = _re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned or content  # fallback to original if we wiped everything


def _extract_json_tool_call(content: str) -> dict | None:
    """Some small models output tool calls as JSON text instead of using the API.
    Detect and parse them so we can execute them properly."""
    s = content.strip()
    # Strip markdown code fences if present
    if s.startswith("```"):
        s = _re.sub(r'^```(?:json)?\s*', '', s)
        s = _re.sub(r'\s*```$', '', s.strip())
    try:
        obj = json.loads(s)
        name = obj.get("name") or obj.get("tool") or obj.get("function")
        args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
        if name and isinstance(name, str):
            return {"name": name, "args": args}
    except Exception:
        pass
    return None


def _run(task: str) -> str:
    llm = _get_coding_llm()
    tools = _get_coding_tools()
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    from src.agents.coding.task_enricher import enrich_task
    enriched_task = enrich_task(task)

    stacks = detect_stacks()
    system_prompt = build_system_prompt(stacks)
    messages = [SystemMessage(system_prompt), HumanMessage(enriched_task)]
    _plan_complete = False

    for _ in range(_MAX_ITERATIONS):
        # Compress context if it exceeds budget — same as orchestrator's "compiling"
        total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
        if total_chars > _CONTEXT_CHAR_BUDGET:
            messages = _compress_specialist_messages(messages, llm)

        invoker = llm if _plan_complete else llm_with_tools
        response = None
        for _ in range(3):
            try:
                response = invoker.invoke(messages)
                break
            except Exception as e:
                err = str(e).lower()
                if any(k in err for k in ("context", "length", "token", "400", "exceed")):
                    if len(messages) > 3:
                        messages = _compress_specialist_messages(messages, llm)
                        invoker = llm if _plan_complete else llm_with_tools
                    else:
                        return "Erreur : le contexte initial est trop volumineux pour ce modèle."
                else:
                    raise
        if response is None:
            return "Erreur : impossible d'invoquer le modèle après compression (contexte trop volumineux)."
        messages.append(response)

        tool_calls = response.tool_calls or []

        # Small models sometimes return tool calls as JSON text instead of using the API
        if not tool_calls and response.content:
            parsed = _extract_json_tool_call(response.content)
            if parsed and parsed["name"] in tool_map:
                tool_calls = [{"name": parsed["name"], "args": parsed["args"], "id": str(uuid.uuid4())}]
            else:
                return _clean_output(response.content) or "Tâche terminée."

        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args", {})

            # Pre-execution hook: show shell commands BEFORE they run
            if _progress_cb and name in _SHELL_PREVIEW_TOOLS:
                try:
                    _progress_cb(f"{name}:before", args)
                except Exception:
                    pass

            # Execute the tool (with session cache for read-only tools)
            from src.infra.tools_cache import session_cache, CACHEABLE_TOOLS
            tool_fn = tool_map.get(name)
            if not tool_fn:
                result = {"status": "error", "error": f"Outil inconnu : {name}"}
            elif name in CACHEABLE_TOOLS and (hit := session_cache.get(name, args)) is not None:
                result = hit
            else:
                try:
                    result = tool_fn.invoke(args)
                    if name in CACHEABLE_TOOLS:
                        session_cache.set(name, args, result)
                    session_cache.on_tool_executed(name)
                except Exception as e:
                    result = {"status": "error", "error": str(e)}

            # Post-execution hook: notify UI of result
            # For shell tools: pass result so UI can show stdout/exit_code
            # For plan/file tools: may return an override dict (HITL)
            if _progress_cb and (name in _PROGRESS_TOOLS or name in _SHELL_PREVIEW_TOOLS):
                skip = (name == "dev_plan_step_done" and
                        isinstance(result, dict) and
                        result.get("status") == "already_done")
                if not skip:
                    try:
                        override = _progress_cb(name, args, result)
                        if isinstance(override, dict):
                            result = override
                    except Exception:
                        pass

            messages.append(ToolMessage(
                content=json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
                tool_call_id=tc["id"],
                name=name,
            ))

            if name == "dev_plan_step_done" and isinstance(result, dict) and result.get("remaining") == 0:
                _plan_complete = True

    return "Tâche interrompue (limite d'itérations atteinte)."  # end of _run
