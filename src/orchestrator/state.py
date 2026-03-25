from typing import Annotated, List
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class GlobalState(TypedDict, total=False):
    messages: Annotated[List, add_messages]
    selected_tools: list
