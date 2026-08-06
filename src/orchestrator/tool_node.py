# src/orchestrator/tool_node.py
"""Exécution des outils, avec cache de session et échecs non fatals.

Une seule question : ce résultat est-il déjà connu, et sinon comment exécuter
sans qu'une exception coûte le tour entier ?
"""
from __future__ import annotations

from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode

from src.orchestrator.resilience import tool_error_to_message

class CachedToolNode:
    """Wraps LangGraph's ToolNode with session-level result caching.
    If ALL tool calls in a batch are cached, skips execution entirely.
    Otherwise executes normally and caches eligible results.
    """

    def __init__(self, tools: list) -> None:
        from src.infra.tools_cache import CACHEABLE_TOOLS, session_cache

        self._inner = ToolNode(tools=tools, handle_tool_errors=tool_error_to_message)
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
            cached_msgs.append(
                ToolMessage(content=hit, tool_call_id=tc["id"], name=name)
            )

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

                self._cache.set(
                    tc["name"], tc.get("args", {}), msg.content, CACHE_TTLS[tc["name"]]
                )
            if tc:
                self._cache.on_tool_executed(tc["name"])

        # Redact sensitive data before it enters the LLM context on cloud backends
        from src.infra.redactor import is_sensitive_path, redact, should_redact
        from src.infra.settings import settings

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
                        # L'artefact porte le résultat non textuel (images,
                        # ressources) : le reconstruire sans lui le perdrait
                        # silencieusement, ce que la redaction ne demande pas.
                        artifact=getattr(msg, "artifact", None),
                        status=getattr(msg, "status", "success"),
                    )
                cleaned.append(msg)
            result = {"messages": cleaned}

        return result
