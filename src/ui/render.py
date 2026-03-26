import time
from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown
from rich import box

from .panels import final_panel, _BOX, _BORDER

_DEBOUNCE = 0.03


def update_live_markdown(live: Live, text: str, debounce_state: dict, cursor: bool = True):
    now = time.time()
    if now - debounce_state.setdefault("last_update", 0.0) > debounce_state.get("DEBOUNCE", _DEBOUNCE):
        live.update(Panel(
            Markdown(text + ("▌" if cursor else "")),
            box=_BOX,
            border_style=_BORDER,
            padding=(1, 2),
        ))
        debounce_state["last_update"] = now


def finalize_live(live: Live, text: str, footer: str = ""):
    content = text + (f"\n\n[dim]{footer}[/dim]" if footer else "")
    live.update(final_panel(content))
