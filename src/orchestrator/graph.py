# src/orchestrator/graph.py
from __future__ import annotations

from datetime import datetime
from typing import List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
from rich.console import Console as RichConsole

_console = RichConsole()

# ── Context budget constants ───────────────────────────────────────────────────
_CONTEXT_LIMITS: dict[str, int] = {
    "ollama":       131_072,
    "ollama_cloud": 128_000,
    "groq":         131_072,
    "gemini":     1_000_000,
}
_COMPACTION_BUFFER = 20_000
_PRUNE_PROTECT     = 40_000
_PRUNE_MINIMUM     = 12_000
_MAX_TOOL_MSG_CHARS = 3_000
_MAX_TOOL_ROUNDS    = 12

# ── Compile callback ───────────────────────────────────────────────────────────
_compile_callback = None
_compressed_this_turn: bool = False


def set_compile_callback(fn) -> None:
    global _compile_callback, _compressed_this_turn
    _compile_callback = fn
    _compressed_this_turn = False  # reset at start of each user turn


# ── Language preference ────────────────────────────────────────────────────────
_lang_pref: str = "fr"


def set_lang_pref(lang: str) -> None:
    global _lang_pref
    _lang_pref = lang


def get_lang_pref() -> str:
    return _lang_pref


# ── Last selected tools (for /debug) ──────────────────────────────────────────
_last_selected_tools: list[str] = []


def get_last_selected_tools() -> list[str]:
    return _last_selected_tools


def _on_compress() -> None:
    if _compile_callback:
        _compile_callback()


# ── Tool-round counter ────────────────────────────────────────────────────────

def _consecutive_tool_rounds(messages: List) -> int:
    """Count total AI→Tool rounds since the last HumanMessage (not just consecutive).
    This catches loops where the LLM interleaves text between tool calls to reset the counter."""
    rounds = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            rounds += 1
    return rounds


# ── Token estimation ───────────────────────────────────────────────────────────

def _estimate_tokens(messages: List) -> int:
    total = 0
    for m in messages:
        content = m.content if isinstance(m.content, str) else str(m.content)
        total += len(content) // 3
    return total


def _usable_budget(backend: str) -> int:
    return _CONTEXT_LIMITS.get(backend, 128_000) - _COMPACTION_BUFFER


def _should_compress(messages: List, backend: str) -> bool:
    return _estimate_tokens(messages) > _usable_budget(backend)


# ── Context helpers ────────────────────────────────────────────────────────────

def _cap_tool_messages(messages: List) -> List:
    out = []
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.content, str) and len(m.content) > _MAX_TOOL_MSG_CHARS:
            m = ToolMessage(
                content=m.content[:_MAX_TOOL_MSG_CHARS] + "\n…[tronqué]",
                tool_call_id=m.tool_call_id,
                name=getattr(m, "name", None),
            )
        out.append(m)
    return out


def _drop_smartest(messages: List) -> List | None:
    """Drop the oldest tool round (AIMessage + its ToolMessages) first.
    Falls back to dropping the oldest non-system message if no tool round found."""
    start = 1 if messages and isinstance(messages[0], SystemMessage) else 0

    for i in range(start, len(messages)):
        m = messages[i]
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            # Find where the tool results for this round end
            j = i + 1
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                j += 1
            if j > i + 1:
                return messages[:i] + messages[j:]

    # No complete tool round found — drop oldest non-system message
    for i in range(start, len(messages)):
        return messages[:i] + messages[i + 1:]

    return None



def _compress_context(messages: List, llm, backend: str = "ollama_cloud") -> tuple[List, List]:
    """Summarise ALL conversation messages into a single dense HumanMessage.

    Returns (compressed_messages, replaced_messages) where replaced_messages
    are the original messages that were summarised — the caller should issue
    RemoveMessage for each to actually persist the compression in LangGraph.
    """
    system_msg = messages[0] if messages and isinstance(messages[0], SystemMessage) else None
    conversation = [m for m in messages if not isinstance(m, SystemMessage)]

    if not conversation:
        return messages, []

    # Build full transcript of everything
    transcript_parts = []
    for m in conversation:
        content = m.content if isinstance(m.content, str) else str(m.content)
        if isinstance(m, HumanMessage):
            transcript_parts.append(f"[USER]: {content[:4000]}")
        elif isinstance(m, AIMessage):
            if content.strip():
                transcript_parts.append(f"[ASSISTANT]: {content[:4000]}")
            for tc in getattr(m, "tool_calls", []) or []:
                args_str = str(tc.get("args", {}))[:1500]
                transcript_parts.append(f"[TOOL CALL] {tc.get('name', '?')}({args_str})")
        elif isinstance(m, ToolMessage):
            name = getattr(m, "name", "tool") or "tool"
            transcript_parts.append(f"[TOOL RESULT] {name}: {content[:3000]}")

    transcript = "\n".join(transcript_parts)

    try:
        prompt = (
            "Tu es un assistant de mémoire pour un agent de code. "
            "Voici la transcription COMPLÈTE d'une session à compresser.\n\n"
            "Génère un résumé DENSE et TECHNIQUE qui permettra à l'agent de continuer "
            "comme si de rien n'était. Préserve ABSOLUMENT :\n"
            "1. La tâche demandée par l'utilisateur (objectif global)\n"
            "2. Le plan d'action — étapes complétées ✓ et restantes ○\n"
            "3. Chaque fichier lu, modifié ou créé — chemin exact + contenu clé\n"
            "4. Le répertoire de travail courant (dernier shell_cd)\n"
            "5. Erreurs rencontrées et solutions appliquées (ou en suspens)\n"
            "6. Dépendances installées, commandes exécutées et leurs résultats\n"
            "7. Choix techniques et pourquoi\n"
            "8. Ce qui était en cours exactement au moment de la coupure\n\n"
            f"TRANSCRIPTION COMPLÈTE :\n{transcript}\n\n"
            "Réponds avec le résumé structuré. Chemins exacts, noms de variables, "
            "valeurs de config — pas de généralités."
        )
        summary_response = llm.invoke([HumanMessage(content=prompt)])
        summary_content = summary_response.content
        if isinstance(summary_content, list):
            summary_content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in summary_content
            )
        summary_msg = HumanMessage(
            content=f"[CONTEXTE COMPRESSÉ — continue la tâche à partir d'ici]\n{summary_content}"
        )
        compressed = ([system_msg] if system_msg else []) + [summary_msg]
        return compressed, conversation
    except Exception:
        # Fallback: drop oldest tool round
        dropped = _drop_smartest(messages) or messages
        kept_ids = {id(m) for m in dropped}
        removed = [m for m in messages if id(m) not in kept_ids]
        return dropped, removed


# ── Cached ToolNode ────────────────────────────────────────────────────────────

class CachedToolNode:
    """Wraps LangGraph's ToolNode with session-level result caching.
    If ALL tool calls in a batch are cached, skips execution entirely.
    Otherwise executes normally and caches eligible results.
    """

    def __init__(self, tools: list) -> None:
        from src.infra.tools_cache import session_cache, CACHEABLE_TOOLS
        self._inner = ToolNode(tools=tools)
        self._cache = session_cache
        self._cacheable = CACHEABLE_TOOLS

    def __call__(self, state: dict, config=None) -> dict:
        last = state["messages"][-1] if state.get("messages") else None
        tool_calls = getattr(last, "tool_calls", None) or []

        # Attempt full-batch cache hit
        cached_msgs: list[ToolMessage] = []
        for tc in tool_calls:
            name, args = tc["name"], tc.get("args", {})
            if name not in self._cacheable:
                cached_msgs = []
                break
            hit = self._cache.get(name, args)
            if hit is None:
                cached_msgs = []
                break
            cached_msgs.append(ToolMessage(content=hit, tool_call_id=tc["id"], name=name))

        if cached_msgs:
            return {"messages": cached_msgs}

        # Execute and cache eligible results
        result = self._inner.invoke(state, config or {})
        tc_by_id = {tc["id"]: tc for tc in tool_calls}

        for msg in result.get("messages", []):
            if not isinstance(msg, ToolMessage):
                continue
            tc = tc_by_id.get(msg.tool_call_id)
            if tc and tc["name"] in self._cacheable:
                from src.infra.tools_cache import CACHE_TTLS
                self._cache.set(tc["name"], tc.get("args", {}), msg.content, CACHE_TTLS[tc["name"]])
            if tc:
                self._cache.on_tool_executed(tc["name"])

        # Redact sensitive data before it enters the LLM context on cloud backends
        from src.infra.settings import settings
        from src.infra.redactor import should_redact, redact, is_sensitive_path
        if should_redact(settings.llm_backend):
            cleaned: list[ToolMessage] = []
            for msg in result.get("messages", []):
                if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                    tc = tc_by_id.get(msg.tool_call_id, {})
                    args = tc.get("args", {}) if tc else {}
                    path = args.get("path", "") or args.get("file_path", "")
                    content = redact(msg.content)
                    if is_sensitive_path(path) and len(content) > 50:
                        content = "[contenu redacté — fichier sensible non transmis au LLM cloud]"
                    msg = ToolMessage(
                        content=content,
                        tool_call_id=msg.tool_call_id,
                        name=getattr(msg, "name", None),
                    )
                cleaned.append(msg)
            result = {"messages": cleaned}

        return result


# ── Orchestrator ───────────────────────────────────────────────────────────────

from src.orchestrator.state import GlobalState
from src.llm.models import make_llm, make_llm_ollama_cloud, make_llm_groq, make_llm_gemini
from src.llm.prompts import build_system_prompt
from src.orchestrator.registry import build_all_tools
from src.infra.checkpoint import build_checkpointer
from src.orchestrator.tool_retriever import ToolRetriever


def _ensure_system_prompt(
    messages: List, selected_tools: List, today: str, plan_mode: bool = False
) -> List:
    import os
    user_name = os.getenv("USER_NAME", "l'utilisateur")
    tool_names = [t.name for t in selected_tools]
    system_msg = SystemMessage(
        content=build_system_prompt(tool_names, today, user_name, plan_mode=plan_mode, lang=_lang_pref)
    )
    if not messages:
        return [system_msg]
    first = messages[0]
    role0 = first.get("type") if isinstance(first, dict) else getattr(first, "type", None)
    if role0 == "system":
        return [system_msg] + messages[1:]
    return [system_msg] + messages


def _chat_node_factory():
    _factories = {
        "groq":         make_llm_groq,
        "ollama_cloud": make_llm_ollama_cloud,
        "ollama":       make_llm,
        "gemini":       make_llm_gemini,
    }
    tools = build_all_tools()
    retriever = ToolRetriever(tools)

    def chatbot(state: GlobalState):
        from src.infra.settings import settings
        from src.ui.plan_mode import is_active as _is_plan_mode, BLOCKED_TOOLS
        backend = settings.llm_backend
        factory = _factories.get(backend, make_llm_ollama_cloud)

        last_human = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
        last_message = state["messages"][-1]
        def _content_to_str(content) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            return str(content)

        if last_human:
            query = _content_to_str(last_human.content)
            if len(query.split()) < 8:
                human_msgs = [_content_to_str(m.content) for m in state["messages"] if isinstance(m, HumanMessage)]
                query = " ".join(human_msgs[-3:])
        else:
            query = _content_to_str(last_message.content) if hasattr(last_message, "content") else str(last_message)
        selected_tools = retriever.get(query)
        global _last_selected_tools
        _last_selected_tools = [t.name for t in selected_tools]

        # Plan mode — strip all write-capable tools
        plan_mode = _is_plan_mode()
        if plan_mode:
            selected_tools = [t for t in selected_tools if t.name not in BLOCKED_TOOLS]

        # Tool-round cap — force text response after _MAX_TOOL_ROUNDS consecutive rounds
        force_text = _consecutive_tool_rounds(state["messages"]) >= _MAX_TOOL_ROUNDS
        if force_text:
            _console.print(f"[dim]  ↩  {_MAX_TOOL_ROUNDS} rounds atteints — synthèse forcée[/dim]")
            llm_with_tools = factory()
        else:
            llm_with_tools = factory().bind_tools(selected_tools)

        messages = state["messages"]
        today = datetime.now().strftime("%Y-%m-%d")
        messages = _ensure_system_prompt(messages, selected_tools, today, plan_mode=plan_mode)

        # Proactive compression before calling the LLM (once per user turn max)
        working = messages
        global _compressed_this_turn
        _state_removals: list = []   # original msgs replaced by summary → RemoveMessage
        _summary_msg = None          # the summary HumanMessage to persist

        if _should_compress(working, backend) and not _compressed_this_turn:
            _compressed_this_turn = True
            _console.print("[dim]  ↩  contexte chargé — compression proactive…[/dim]")
            _on_compress()
            plain_llm = factory()
            working = _cap_tool_messages(working)
            working, _state_removals = _compress_context(working, plain_llm, backend)
            # The summary msg is the first HumanMessage in the compressed list
            _summary_msg = next(
                (m for m in working if isinstance(m, HumanMessage)
                 and "[CONTEXTE COMPRESSÉ" in str(m.content)),
                None,
            )

        capped = False
        compressed = False

        while True:
            try:
                response = llm_with_tools.invoke(working)

                usage = getattr(response, "usage_metadata", None)
                if usage:
                    from src.ui.token_gauge import update_usage
                    update_usage(usage)

                break

            except Exception as e:
                err = str(e).lower()
                if "context" not in err and "length" not in err and "token" not in err:
                    raise

                if not capped:
                    capped = True
                    working = _cap_tool_messages(working)
                    _console.print("[dim]  ↩  contexte trop long — tronquage des résultats tools…[/dim]")

                elif not compressed:
                    compressed = True
                    if not _compressed_this_turn:
                        _compressed_this_turn = True
                        _on_compress()
                    plain_llm = factory()
                    working, removed = _compress_context(working, plain_llm, backend)
                    _state_removals.extend(r for r in removed if r not in _state_removals)
                    _summary_msg = next(
                        (m for m in working if isinstance(m, HumanMessage)
                         and "[CONTEXTE COMPRESSÉ" in str(m.content)),
                        _summary_msg,
                    )
                    _console.print("[dim]  ↩  contexte compressé — reprise…[/dim]")

                else:
                    reduced = _drop_smartest(working)
                    if reduced is None or len(reduced) <= 1:
                        raise
                    working = reduced
                    _console.print(f"[dim]  ↩  drop tool round ({len(working)} messages restants)…[/dim]")

        # Persist compression to LangGraph state so subsequent chatbot calls
        # start with the compressed history, not the original bloated one.
        from langchain_core.messages import RemoveMessage
        result: list = []
        if _state_removals:
            result += [RemoveMessage(id=m.id) for m in _state_removals if getattr(m, "id", None)]
            if _summary_msg:
                result.append(_summary_msg)
        result.append(response)
        return {"messages": result}

    return chatbot, tools


def build_orchestrator():
    chatbot, tools = _chat_node_factory()

    g = StateGraph(GlobalState)
    g.add_node("chatbot", chatbot)
    g.add_node("tools", CachedToolNode(tools))

    g.add_edge(START, "chatbot")
    g.add_conditional_edges("chatbot", tools_condition)
    g.add_edge("tools", "chatbot")

    return g.compile(checkpointer=build_checkpointer())
