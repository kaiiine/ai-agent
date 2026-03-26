from dotenv import load_dotenv
from rich.console import Console
from rich.rule import Rule
from rich.text import Text
from rich.align import Align

from src.orchestrator.graph import build_orchestrator
from src.ui.config import SessionConfig
from src.ui.panels import banner, ACCENT
from src.ui.streaming import stream_once

load_dotenv()
console = Console()


def run_cli():
    graph = build_orchestrator()
    cfg = SessionConfig()
    state = {"messages": []}

    console.clear()
    console.print(banner())

    try:
        while True:
            stream_once(graph, state, cfg)
    except KeyboardInterrupt:
        console.print()
        console.print(Rule("à bientôt", characters="·", style=f"dim {ACCENT}"))
        console.print()
