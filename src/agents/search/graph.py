from langgraph.graph import StateGraph
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
from ...llm.models import make_llm
from ...orchestrator.state import GlobalState
from .tools import build_search_tool

def build_search_graph():
    llm = make_llm()
    tool = build_search_tool()
    tools = [tool]
    llm_with_tools = llm.bind_tools(tools)

    def chatbot(state: GlobalState):
        return {"messages": [llm_with_tools.invoke(state["messages"])]}

    g = StateGraph(GlobalState)
    g.add_node("chatbot", chatbot)
    g.add_node("tools", ToolNode(tools=tools))
    g.add_conditional_edges("chatbot", tools_condition)
    g.add_edge("tools", "chatbot")
    g.add_edge(START, "chatbot")
    return g.compile()
