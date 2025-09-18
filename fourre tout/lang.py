from typing import Annotated
from langchain_tavily import TavilySearch
from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
#Comment s'appelle l'insecte vert tout fin qui ressemble a un bout de baton ? C'est quoi sa taille max
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt
load_dotenv()

llm = ChatOllama(model="qwen2.5:7b", temperature=0, streaming=True)
memory = InMemorySaver()


class State(TypedDict):
    messages: Annotated[list, add_messages]

graph_builder = StateGraph(State)

tool = TavilySearch(max_results=2)
tools = [tool]
llm_with_tools = llm.bind_tools(tools)

def chatbot(state: State):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

graph_builder.add_node("chatbot", chatbot)

tool_node = ToolNode(tools=[tool])
graph_builder.add_node("tools", tool_node)

graph_builder.add_conditional_edges(
    "chatbot",
    tools_condition,
)
# Any time a tool is called, we return to the chatbot to decide the next step
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")
graph = graph_builder.compile(checkpointer=memory)


def stream_graph_updates(user_input: str):
    state = {"messages": [{"role": "user", "content": user_input}]}
    saw_tool = False  # (optionnel) si tu veux n’afficher qu’après un tool

    for msg, meta in graph.stream(state, stream_mode="messages", config={"configurable": {"thread_id": "1"}},):
        node = meta.get("langgraph_node")  # nom du nœud courant

        # Si un tool s'est exécuté, on le note (et on n'affiche rien)
        if isinstance(msg, ToolMessage):
            saw_tool = True
            continue

        # On n'affiche que les chunks de l'assistant venant du nœud chatbot
        if isinstance(msg, AIMessageChunk) and node == "chatbot":
            # si tu veux n'afficher qu'après un tool, garde: if saw_tool and ...
            print(msg.content, end="", flush=True)

    print()  # newline



while True:
    try:
        user_input = input("User: ")
        if user_input.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break

        stream_graph_updates(user_input)
    except:
        # fallback if input() is not available
        user_input = "What do you know about LangGraph?"
        print("User: " + user_input)
        stream_graph_updates(user_input)
        break
