from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.table import Table
from rich.rule import Rule
from rich.console import Group
from rich.markdown import Markdown
from rich import box

from .config import SessionConfig

_BOX = box.SIMPLE_HEAD
ACCENT = "color(214)"
_BORDER = f"dim {ACCENT}"

def _c(line: str, style: str) -> Align:
    return Align.center(Text(line, style=style))


_ROBOT = [
    "  ████████████  ",
    "  █  ▪    ▪  █  ",
    "  █          █  ",
    "  ████████████  ",
    "    ████  ████  ",
    "    █        █  ",
]

_CLOUDS = [
    ("*      ░░░ ░░░           ░░░░░░      *", "dim"),
    ("     ░░░░░░░░░░        ░░░░░░░░░      ", "dim"),
    ("  *    ░░░ ░░░    *      ░░░░░░    *  ", "dim"),
]


def banner():
    dim_o  = f"dim {ACCENT}"
    bold_o = f"bold {ACCENT}"

    return Group(
        Rule(characters="·", style=dim_o),
        Text(""),
        _c(_CLOUDS[0][0], _CLOUDS[0][1]),
        _c(_CLOUDS[1][0], _CLOUDS[1][1]),
        _c(_CLOUDS[2][0], _CLOUDS[2][1]),
        Text(""),
        *[_c(line, bold_o) for line in _ROBOT],
        Text(""),
        _c(_CLOUDS[2][0], _CLOUDS[2][1]),
        _c(_CLOUDS[1][0], _CLOUDS[1][1]),
        _c(_CLOUDS[0][0], _CLOUDS[0][1]),
        Text(""),
        Rule(Text("A  X  O  N", style=bold_o), characters="·", style=dim_o),
        Text(""),
        _c("kaine's intelligent agent",                 dim_o),
        Text(""),
        _c("help · attach · clear · new · save · q",    "dim"),
        Text(""),
    )


def live_panel_initial(dots: int = 0):
    dot_str = ("." * dots).ljust(3)
    t = Text()
    t.append("  thinking", style=_BORDER)
    t.append(dot_str, style=f"bold {ACCENT}")
    return Panel(t, box=_BOX, border_style=_BORDER, padding=(0, 1))


def tool_call_panel(tool_name: str):
    t = Text()
    t.append("  ✓  ", style=f"bold {ACCENT}")
    t.append(tool_name, style="dim")
    return Panel(t, box=_BOX, border_style=_BORDER, padding=(0, 1))


def final_panel(md_text: str):
    return Panel(
        Markdown(md_text),
        box=_BOX,
        border_style=_BORDER,
        padding=(1, 2),
    )


def command_panel(text: str, error: bool = False):
    return Panel(
        Text(text),
        box=_BOX,
        border_style="red" if error else _BORDER,
        padding=(0, 1),
    )


def config_table(cfg: SessionConfig) -> Table:
    tbl = Table(box=_BOX, show_header=True, header_style="dim")
    tbl.add_column("param", style="dim", no_wrap=True)
    tbl.add_column("value", style="white")
    tbl.add_row("thread_id", cfg.thread_id)
    tbl.add_row("model", cfg.model)
    tbl.add_row("temperature", str(cfg.temp))
    tbl.add_row("lang", cfg.lang_pref)
    return tbl
