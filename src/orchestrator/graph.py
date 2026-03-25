# src/orchestrator/graph.py
from __future__ import annotations

from datetime import datetime
from typing import List

from langchain_core.messages import SystemMessage, trim_messages
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from src.orchestrator.state import GlobalState
from src.llm.models import make_llm, make_llm_ollama_cloud, make_llm_groq
from src.llm.prompts import SYSTEM_PROMPT
from src.orchestrator.registry import build_all_tools
from src.infra.checkpoint import build_checkpointer
from src.orchestrator.tool_retriever import ToolRetriever


def _ensure_system_prompt(messages: List, tools_names: str, today: str) -> List:
    system_msg = SystemMessage(content=SYSTEM_PROMPT.format(tools_available=tools_names, today=today))
    if not messages:
        return [system_msg]
    first = messages[0]
    role0 = first.get("type") if isinstance(first, dict) else getattr(first, "type", None)
    if role0 == "system":
        # Remplace le system prompt existant avec les tools sélectionnés à jour
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

        last_message = state["messages"][-1]
        query = last_message.content if hasattr(last_message, "content") else str(last_message)
        selected_tools = retriever.get(query)

        llm_with_tools = factory().bind_tools(selected_tools)

        messages = state["messages"]
        today = datetime.now().strftime("%Y-%m-%d")
        tools_names = ", ".join(t.name for t in selected_tools)
        messages = _ensure_system_prompt(messages, tools_names, today)
        messages = trim_messages(
            messages,
            max_tokens=100_000,
            strategy="last",
            token_counter=lambda msgs: sum(len(str(getattr(m, "content", m))) // 4 for m in msgs),
            include_system=True,
            allow_partial=False,
        )
        response = llm_with_tools.invoke(messages)
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
