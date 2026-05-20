import re
from dotenv import load_dotenv
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from src.orchestrator.graph import build_orchestrator
from src.ui.config import SessionConfig
from src.ui.panels import banner, command_panel, final_panel, ACCENT
from src.ui.streaming import stream_once
from src.infra.checkpoint import (
    load_last_thread, save_last_thread, get_recent_messages,
    load_thread_cwd, save_thread_cwd,
)
from src.agents.shell.tools import get_cwd, set_cwd

load_dotenv()
console = Console(highlight=True, emoji=True)


_HISTORY_LIMIT = 50


def _show_specialist_trace(content: str) -> None:
    from rich.panel import Panel
    from rich.text import Text as RText

    m = re.search(r'\[SPECIALIST-TRACE\](.*?)\[/SPECIALIST-TRACE\]', content, re.DOTALL)
    result_text = content
    trace_lines: dict = {}

    if m:
        raw = m.group(1).strip()
        result_text = content[m.end():].strip()
        for line in raw.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                trace_lines[k.strip()] = v.strip()

    body = RText()
    if "cwd" in trace_lines:
        body.append("  📁  ", style=f"dim {ACCENT}")
        body.append(trace_lines["cwd"] + "\n", style="dim")
    if "files" in trace_lines:
        for f in trace_lines["files"].split(","):
            body.append("  ✓  ", style="bold green")
            body.append(f.strip() + "\n", style="dim")
    if "plan" in trace_lines:
        for step in trace_lines["plan"].split("|"):
            done = step.startswith("✓")
            icon = "  ✓  " if done else "  ○  "
            body.append(icon, style="bold green" if done else "dim")
            body.append(step[1:].strip() + "\n", style="dim")
    if result_text:
        body.append("\n" + result_text[:3000], style="dim")

    console.print(Panel(
        body,
        border_style=f"dim {ACCENT}",
        title="[dim]agent code[/dim]",
        title_align="left",
        padding=(0, 2),
    ))


def _show_resume(thread_id: str) -> None:
    """Affiche l'historique complet du thread au démarrage."""
    messages = get_recent_messages(thread_id)
    if not messages:
        return

    visible = [m for m in messages if m["role"] in ("human", "ai", "coding_agent") and m["content"].strip()]
    if not visible:
        return

    hidden = len(visible) - _HISTORY_LIMIT
    if hidden > 0:
        visible = visible[-_HISTORY_LIMIT:]

    console.print(Rule("reprise de session", characters="·", style=f"dim {ACCENT}"))
    console.print()

    if hidden > 0:
        console.print(Text(f"  … {hidden} messages plus anciens", style="dim"))
        console.print()

    for m in visible:
        role    = m["role"]
        content = m["content"].strip()
        if role == "human":
            label = Text()
            label.append("  ›  ", style=f"bold {ACCENT}")
            label.append(content, style=f"bold {ACCENT}")
            console.print(label)
        elif role == "ai":
            clean = re.sub(
                r'<axon:plan>.*?</axon:plan>\s*', '', content, flags=re.DOTALL
            ).strip()
            if clean:
                console.print(final_panel(clean))
        elif role == "coding_agent":
            _show_specialist_trace(content)

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
        saved_cwd = load_thread_cwd(last)
        if saved_cwd:
            set_cwd(saved_cwd)

    console.clear()
    console.print(banner())

    if last:
        _show_resume(last)

    try:
        while True:
            stream_once(graph, state, cfg)
            # Persiste le thread actif et le cwd courant après chaque échange
            save_last_thread(cfg.thread_id)
            save_thread_cwd(cfg.thread_id, str(get_cwd()))
    except KeyboardInterrupt:
        save_last_thread(cfg.thread_id)
        save_thread_cwd(cfg.thread_id, str(get_cwd()))
        console.print()
        console.print(Rule("à bientôt", characters="·", style=f"dim {ACCENT}"))
        console.print()
