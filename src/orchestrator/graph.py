# src/orchestrator/graph.py
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
from src.orchestrator.state import GlobalState
from src.llm.models import make_llm
from src.orchestrator.registry import build_all_tools
from src.infra.checkpoint import build_checkpointer

def build_orchestrator():
    llm = make_llm()          # LLM unique (Ollama)
    tools = build_all_tools()               # tous tes tools
    llm_with_tools = llm.bind_tools(tools)  # binding

    def chatbot(state: GlobalState):
        # LLM décide: répondre direct OU appeler un tool
        return {"messages": [llm_with_tools.invoke(state["messages"])]}
        

    g = StateGraph(GlobalState)
    g.add_node("chatbot", chatbot)
    g.add_node("tools", ToolNode(tools=tools))

    # Si le LLM appelle un tool -> ToolNode -> retour au chatbot
    g.add_conditional_edges("chatbot", tools_condition)
    g.add_edge("tools", "chatbot")

    # Entrée
    g.add_edge(START, "chatbot")

    return g.compile(checkpointer=build_checkpointer())
