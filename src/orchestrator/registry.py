# src/tools/registry.py
from langchain_core.tools import BaseTool
from typing import List

# Tools concrets
from src.agents.search.tools import build_search_tool
from src.agents.weather.tools import get_weather_by_city

def build_all_tools() -> List[BaseTool]:
    tools: List[BaseTool] = []
    # Web search
    tools.append(build_search_tool())
    tools.append(get_weather_by_city)
    return tools
