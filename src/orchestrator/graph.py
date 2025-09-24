# src/orchestrator/graph.py
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import SystemMessage
from src.orchestrator.state import GlobalState
from src.llm.models import make_llm
from src.llm.prompts import SYSTEM_PROMPT
from src.orchestrator.registry import build_all_tools
from src.utils.tools import get_tool_names, get_tools_catalog
from src.infra.checkpoint import build_checkpointer

def build_orchestrator():
    llm = make_llm()
    tools = build_all_tools()
    llm_with_tools = llm.bind_tools(tools)

    def chatbot(state: GlobalState):
        messages = state["messages"]
        
        # Ajouter le prompt système si pas déjà présent
        if not messages or messages[0].type != "system":
            system_msg = SystemMessage(content=SYSTEM_PROMPT.format(tools_available=get_tool_names()))
            messages = [system_msg] + messages
        
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    g = StateGraph(GlobalState)
    g.add_node("chatbot", chatbot)
    g.add_node("tools", ToolNode(tools=tools))

    g.add_conditional_edges("chatbot", tools_condition)
    g.add_edge("tools", "chatbot")
    g.add_edge(START, "chatbot")

    return g.compile(checkpointer=build_checkpointer())
