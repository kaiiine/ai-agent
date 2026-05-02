import re

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



_SCENE = [
    # ciel — nuages pixel-art remplis ░ + étoiles
    ("  *        ░░░░░░░                   *        *    ", "dim"),
    ("      ░░   ░░░░░░░░░░░        *                    ", "dim"),
    ("    ░░░░░░░░░░░░░░░░░░░     ░░░░░░░░░          *   ", "dim"),
    ("  *                        ░░░░░░░░░░░░░░           ", "dim"),
    ("              *            ░░░░░░░░░░░░░░░░    *    ", "dim"),
    # axolotl — bold orange uniforme
    ("⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⠐⡄⠰⠤⠀⠀⠀⠀⠀⠀", f"bold {ACCENT}"),
    ("⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢐⠹⣀⣆⠚⠂⢱⡀⠀⠀⠀⠀", f"bold {ACCENT}"),
    ("⢀⢀⡄⡀⢄⠀⡠⠔⠊⠉⠉⠉⠉⢲⣷⡿⣠⣗⣡⠂⠀⠀", f"bold {ACCENT}"),
    ("⡘⣈⢣⡰⣈⠎⠀⠀⠀⠀⠀⢿⣦⡀⢙⣟⣽⢁⡜⡠⡨⢤", f"bold {ACCENT}"),
    ("⢱⠒⡏⢯⣿⢷⢀⠴⡶⠊⠁⠀⠀⠁⠀⢹⠛⢏⢫⠐⠁⠃", f"bold {ACCENT}"),
    ("⠂⣁⠼⣾⣿⠉⠀⠀⠀⠀⠀⢎⠍⠒⠴⠧⠯⡈⠉⠀⠀⡄", f"bold {ACCENT}"),
    ("⠀⠣⠕⡞⣹⡗⣤⠄⠀⠀⠀⠀⠁⠀⠀⠀⠀⠈⢉⡵⢠⠃", f"bold {ACCENT}"),
    ("⠀⠀⠀⠈⠀⠀⠑⠀⠤⠤⠤⢄⠀⠀⠀⠀⠠⢞⡓⠈⣀⠄", f"bold {ACCENT}"),
    ("⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠑⠒⠒⠈⠉⠁⠀⠀⠀", f"bold {ACCENT}"),
    # sol
    ("  ───────────────────────────────────────  ", "dim"),
]


def banner():
    dim_o  = f"dim {ACCENT}"
    bold_o = f"bold {ACCENT}"

    return Group(
        Rule(characters="·", style=dim_o),
        Text(""),
        *[_c(line, style) for line, style in _SCENE],
        Text(""),
        Rule(Text("A  X  O  N", style=bold_o), characters="·", style=dim_o),
        Text(""),
        _c("kaine's intelligent agent",              dim_o),
        Text(""),
        _c("help · attach · clear · new · save · q", "dim"),
        Text(""),
    )


# ── Panels ────────────────────────────────────────────────────────────────────

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


def plan_panel(steps_text: str) -> Panel:
    """Renders a structured plan block emitted by the LLM (<axon:plan> tag)."""
    lines = [l.strip() for l in steps_text.splitlines() if l.strip()]
    body = Text()
    for i, line in enumerate(lines):
        clean = re.sub(r"^[-*•]\s*", "", line).strip()
        clean = re.sub(r"^\d+\.\s*", "", clean).strip()
        if not clean:
            continue
        body.append(f"  {i + 1}.  ", style=f"bold {ACCENT}")
        body.append(clean, style="white")
        if i < len(lines) - 1:
            body.append("\n")
    return Panel(
        body,
        box=_BOX,
        border_style=f"dim {ACCENT}",
        title="[dim]plan[/dim]",
        title_align="left",
        padding=(0, 2),
    )


def compile_panel(dots: int = 0) -> Panel:
    """Shown while the LLM compresses the context window."""
    dot_str = ("." * (dots % 4)).ljust(3)
    t = Text()
    t.append("  compiling", style=_BORDER)
    t.append(dot_str, style=f"bold {ACCENT}")
    t.append("  ", style="dim")
    t.append("résumé du contexte", style="dim")
    return Panel(t, box=_BOX, border_style=_BORDER, padding=(0, 1))


def command_panel(text: str, error: bool = False):
    return Panel(
        Text(text),
        box=_BOX,
        border_style="red" if error else _BORDER,
        padding=(0, 1),
    )


def config_table(cfg: SessionConfig) -> Table:
    from src.infra.settings import settings

    def _active_model(s) -> str:
        if s.llm_backend == "groq":         return s.groq_model
        if s.llm_backend == "ollama_cloud": return s.ollama_cloud_model
        return s.ollama_model

    tbl = Table(box=_BOX, show_header=True, header_style="dim")
    tbl.add_column("param",  style="dim",   no_wrap=True)
    tbl.add_column("value",  style="white")
    tbl.add_row("thread_id",   cfg.thread_id)
    tbl.add_row("backend",     settings.llm_backend)
    tbl.add_row("model",       _active_model(settings))
    tbl.add_row("temperature", str(settings.temperature))
    tbl.add_row("lang",        cfg.lang_pref)
    return tbl