import time
from rich.live import Live
from .panels import final_panel

def update_live_markdown(live: Live, text: str, node_title: str, debounce_state: dict, cursor: bool = True):
    from .panels import Panel
    from rich.markdown import Markdown
    now = time.time()
    if now - debounce_state.setdefault("last_update", 0.0) > debounce_state.get("DEBOUNCE", 0.03):
        live.update(Panel(
            Markdown(text + ("▌" if cursor else "")),
            title=f"🤖 Agent · nœud `{node_title}`",
            border_style="cyan",
            padding=(1, 2)
        ))
        debounce_state["last_update"] = now

def finalize_live(live: Live, text: str, footer: str = ""):
    live.update(final_panel(text + (("\n\n" + footer) if footer else "")))
