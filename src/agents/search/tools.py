from langchain_tavily import TavilySearch
from ...infra.settings import settings

def build_search_tool():
    # Regarder comment implémenter SearXNG
    return TavilySearch(max_results=settings.search_max_results)
