from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from src.orchestrator.graph import build_orchestrator
from src.ui.config import SessionConfig
from src.ui.panels import banner, command_panel, ACCENT, _BOX, _BORDER
from src.ui.streaming import stream_once
from src.infra.checkpoint import (
    load_last_thread, save_last_thread, get_recent_messages,
)

load_dotenv()
console = Console(highlight=True, emoji=True)

_RESUME_MESSAGES = 6   # nombre de messages à afficher au démarrage


def _show_resume(thread_id: str) -> None:
    """Affiche les derniers messages du thread repris."""
    messages = get_recent_messages(thread_id, n=_RESUME_MESSAGES)
    if not messages:
        return

    _ROLE_STYLE = {
        "human": (f"bold {ACCENT}", "›"),
        "ai":    ("dim white",      "·"),
        "tool":  ("dim",            "⚙"),
    }

    console.print(Rule("reprise de session", characters="·", style=f"dim {ACCENT}"))
    console.print()

    for m in messages:
        role    = m["role"]
        content = m["content"].strip()
        if not content:
            continue
        style, icon = _ROLE_STYLE.get(role, ("dim", "?"))
        label = Text()
        label.append(f"  {icon}  ", style=f"bold {ACCENT}")
        label.append(content, style=style)
        console.print(label)

    console.print()
    console.print(
        Text(f"  thread : {thread_id}", style="dim"),
        Text("  ·  /history pour changer  ·  /new pour recommencer", style="dim"),
    )
    console.print()


def run_cli():
    graph = build_orchestrator()
    cfg   = SessionConfig()
    state = {"messages": []}

    # ── Reprise du dernier thread ──────────────────────────────────────────────
    last = load_last_thread()
    if last:
        cfg.thread_id = last

    console.clear()
    console.print(banner())

    if last:
        _show_resume(last)

    try:
        while True:
            stream_once(graph, state, cfg)
            # Persiste le thread actif après chaque échange
            save_last_thread(cfg.thread_id)
    except KeyboardInterrupt:
        save_last_thread(cfg.thread_id)
        console.print()
        console.print(Rule("à bientôt", characters="·", style=f"dim {ACCENT}"))
        console.print()
