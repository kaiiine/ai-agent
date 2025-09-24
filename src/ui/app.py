from dotenv import load_dotenv
from rich.console import Console
from rich.align import Align
from rich.panel import Panel

from src.orchestrator.graph import build_orchestrator
from src.utils.tools import get_tools_catalog, get_tool_names
from src.ui.config import SessionConfig
from src.ui.panels import banner, system_info, instructions
from src.ui.streaming import stream_once
from src.llm.prompts import SYSTEM_PROMPT

console = Console()

def run_cli():
    load_dotenv()
    graph = build_orchestrator()
    cfg = SessionConfig()

    console.clear()
    console.print(banner())
    console.print(system_info())
    console.print()
    console.print(instructions())
    console.print()

    # État initial avec identité
    state = {
    "messages": [
        {
            "role": "system",
            "content": (SYSTEM_PROMPT.format(tools_available=get_tool_names()))
        }
    ]
}


    try:
        while True:
            stream_once(graph, state, cfg)
    except KeyboardInterrupt:
        goodbye = Panel(Align.center("👋 Au revoir ! À bientôt."), border_style="yellow", title="Fermeture")
        console.print(goodbye)
