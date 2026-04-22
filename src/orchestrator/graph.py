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

# ── Compile callback ───────────────────────────────────────────────────────────
_compile_callback = None


def set_compile_callback(fn) -> None:
    global _compile_callback
    _compile_callback = fn


def _on_compress() -> None:
    if _compile_callback:
        _compile_callback()


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


def _compress_context(messages: List, llm, backend: str = "ollama_cloud") -> List:
    system_msg = messages[0] if messages and isinstance(messages[0], SystemMessage) else None
    conversation = messages[1:] if system_msg else messages

    protect_budget = max(_PRUNE_MINIMUM, min(_PRUNE_PROTECT, _usable_budget(backend) // 4))
    recent: list = []
    used = 0
    for m in reversed(conversation):
        cost = _estimate_tokens([m])
        if used + cost > protect_budget and len(recent) >= 2:
            break
        recent.insert(0, m)
        used += cost

    to_summarize = conversation[:len(conversation) - len(recent)]

    if not to_summarize:
        return _drop_smartest(messages) or messages

    excerpt = "\n".join(
        f"{type(m).__name__}: {(m.content if isinstance(m.content, str) else str(m.content))[:400]}"
        for m in to_summarize
        if hasattr(m, "content")
    )

    try:
        summary_response = llm.invoke([HumanMessage(content=(
            "Résume ces échanges en préservant :\n"
            "- Les informations factuelles, décisions, actions effectuées\n"
            "- Les fichiers, chemins et ressources mentionnés\n"
            "- L'état des tâches en cours\n\n"
            f"Échanges :\n{excerpt}\n\n"
            "Réponds UNIQUEMENT avec le résumé condensé."
        ))])
        summary_msg = HumanMessage(
            content=f"[Résumé de la conversation précédente]\n{summary_response.content}"
        )
        return ([system_msg] if system_msg else []) + [summary_msg] + recent
    except Exception:
        return _drop_smartest(messages) or messages


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
        result = self._inner(state) if config is None else self._inner(state, config)
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
        content=build_system_prompt(tool_names, today, user_name, plan_mode=plan_mode)
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
        if last_human:
            query = last_human.content
            if len(query.split()) < 8:
                human_msgs = [m.content for m in state["messages"] if isinstance(m, HumanMessage)]
                query = " ".join(human_msgs[-3:])
        else:
            query = last_message.content if hasattr(last_message, "content") else str(last_message)
        selected_tools = retriever.get(query)

        # Plan mode — strip all write-capable tools
        plan_mode = _is_plan_mode()
        if plan_mode:
            selected_tools = [t for t in selected_tools if t.name not in BLOCKED_TOOLS]

        llm_with_tools = factory().bind_tools(selected_tools)

        messages = state["messages"]
        today = datetime.now().strftime("%Y-%m-%d")
        messages = _ensure_system_prompt(messages, selected_tools, today, plan_mode=plan_mode)

        # Proactive compression before calling the LLM
        working = messages
        if _should_compress(working, backend):
            _console.print("[dim]  ↩  contexte chargé — compression proactive…[/dim]")
            _on_compress()
            plain_llm = factory()
            working = _cap_tool_messages(working)
            working = _compress_context(working, plain_llm, backend)

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
                    _on_compress()
                    plain_llm = factory()
                    working = _compress_context(working, plain_llm, backend)
                    _console.print("[dim]  ↩  contexte compressé — reprise…[/dim]")

                else:
                    reduced = _drop_smartest(working)
                    if reduced is None or len(reduced) <= 1:
                        raise
                    working = reduced
                    _console.print(f"[dim]  ↩  drop tool round ({len(working)} messages restants)…[/dim]")

        return {"messages": [response]}

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
