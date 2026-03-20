# src/orchestrator/graph.py
from __future__ import annotations

from datetime import datetime
from typing import List

from langchain_core.messages import SystemMessage, trim_messages
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from src.orchestrator.state import GlobalState
from src.llm.models import make_llm, make_llm_ollama_cloud
from src.llm.prompts import SYSTEM_PROMPT
from src.orchestrator.registry import build_all_tools
from src.infra.checkpoint import build_checkpointer
from src.utils.tools import get_tool_names


def _ensure_system_prompt(messages: List, tools_names: str, today: str) -> List:
    if not messages:
        return [SystemMessage(content=SYSTEM_PROMPT.format(tools_available=tools_names, today=today))]
    first = messages[0]
    role0 = first.get("type") if isinstance(first, dict) else getattr(first, "type", None)
    if role0 != "system":
        return [SystemMessage(content=SYSTEM_PROMPT.format(tools_available=tools_names, today=today))] + messages
    return messages


def _chat_node_factory():
    llm = make_llm_ollama_cloud()
    tools = build_all_tools()
    llm_with_tools = llm.bind_tools(tools)

    def chatbot(state: GlobalState):
        messages = state["messages"]
        today = datetime.now().strftime("%Y-%m-%d")
        tools_names = get_tool_names()
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
