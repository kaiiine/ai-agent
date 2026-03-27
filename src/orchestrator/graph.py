# src/orchestrator/graph.py
from __future__ import annotations

from datetime import datetime
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
from rich.console import Console as RichConsole

_console = RichConsole()

_MAX_TOOL_MSG_CHARS = 3_000


def _cap_tool_messages(messages: List) -> List:
    out = []
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.content, str) and len(m.content) > _MAX_TOOL_MSG_CHARS:
            truncated = m.content[:_MAX_TOOL_MSG_CHARS] + "\n…[tronqué]"
            m = ToolMessage(content=truncated, tool_call_id=m.tool_call_id, name=getattr(m, "name", None))
        out.append(m)
    return out


def _drop_oldest_non_system(messages: List) -> List | None:
    """Drop the oldest non-system message. Returns None if nothing left to drop."""
    for i in range(1, len(messages)):
        return messages[:i] + messages[i + 1:]
    return None

from src.orchestrator.state import GlobalState
from src.llm.models import make_llm, make_llm_ollama_cloud, make_llm_groq
from src.llm.prompts import SYSTEM_PROMPT
from src.orchestrator.registry import build_all_tools
from src.infra.checkpoint import build_checkpointer
from src.orchestrator.tool_retriever import ToolRetriever


def _ensure_system_prompt(messages: List, tools_names: str, today: str) -> List:
    import os
    user_name = os.getenv("USER_NAME", "l'utilisateur")
    system_msg = SystemMessage(content=SYSTEM_PROMPT.format(tools_available=tools_names, today=today, user_name=user_name))
    if not messages:
        return [system_msg]
    first = messages[0]
    role0 = first.get("type") if isinstance(first, dict) else getattr(first, "type", None)
    if role0 == "system":
        # rempace le system prompt existant avec les tools sélectionnés à jour
        return [system_msg] + messages[1:]
    return [system_msg] + messages


def _chat_node_factory():
    _factories = {
        "groq":         make_llm_groq,
        "ollama_cloud": make_llm_ollama_cloud,
        "ollama":       make_llm,
    }
    tools = build_all_tools()
    retriever = ToolRetriever(tools)

    def chatbot(state: GlobalState):
        # Re-read settings on every call so /model, /temp, /backend take effect immediately
        from src.infra.settings import settings
        factory = _factories.get(settings.llm_backend, make_llm_ollama_cloud)

        last_human = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
        last_message = state["messages"][-1]
        if last_human:
            query = last_human.content
            # Si le message est trop court on enrichit avec les HumanMessages précédents pour que le ToolRetriever garde le contexte de la conversation.
            if len(query.split()) < 8:
                human_msgs = [m.content for m in state["messages"] if isinstance(m, HumanMessage)]
                query = " ".join(human_msgs[-3:])  # 3 derniers messages humains
        else:
            query = last_message.content if hasattr(last_message, "content") else str(last_message)
        selected_tools = retriever.get(query)

        llm_with_tools = factory().bind_tools(selected_tools)

        messages = state["messages"]
        today = datetime.now().strftime("%Y-%m-%d")
        tools_names = ", ".join(t.name for t in selected_tools)
        messages = _ensure_system_prompt(messages, tools_names, today)
        working = messages
        capped = False
        while True:
            try:
                response = llm_with_tools.invoke(working)
                break
            except Exception as e:
                if "context" not in str(e).lower() and "length" not in str(e).lower():
                    raise
                if not capped:
                    # on tronque les ToolsMessages trop volumineux
                    capped = True
                    working = _cap_tool_messages(messages)
                    _console.print("[dim]  ↩  contexte trop long — tronquage des résultats tools et retry…[/dim]")
                else:
                    # supprime le message le plus ancien (hors system)
                    reduced = _drop_oldest_non_system(working)
                    if reduced is None or len(reduced) <= 1:
                        raise
                    working = reduced
                    _console.print(f"[dim]  ↩  toujours trop long — suppression d'un ancien message ({len(working)} restants)…[/dim]")

        return {"messages": [response]}

    return chatbot, tools


def build_orchestrator():
    chatbot, tools = _chat_node_factory()

    g = StateGraph(GlobalState)
    g.add_node("chatbot", chatbot)
    g.add_node("tools", ToolNode(tools=tools))

    g.add_edge(START, "chatbot")
    g.add_conditional_edges("chatbot", tools_condition)
    g.add_edge("tools", "chatbot")

    return g.compile(checkpointer=build_checkpointer())
