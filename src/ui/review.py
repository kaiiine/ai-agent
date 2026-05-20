"""HITL review UI — shows diffs, arrow-key navigation to approve/reject/refine."""
from __future__ import annotations

import difflib
import os
import sys
from pathlib import Path
from typing import List, Tuple

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from src.agents.coding.pending import FileChange, pending_changes
from src.agents.notebook.tools import CellChange, pending_cell_changes, apply_cell_change
from .panels import ACCENT, _BOX, _BORDER
from .picker import _ACCENT_PT

console = Console()


def _supports_raw_tty() -> bool:
    """True when stdin/stdout are real TTYs and raw-mode is available."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if os.environ.get("TERM", "") in ("", "dumb"):
        return False
    try:
        import termios  # noqa
        return True
    except ImportError:
        return False


def _fallback_selector(choices: List[Tuple[str, str]]) -> str:
    """Simple numbered fallback for terminals that don't support raw-mode."""
    console.print()
    for i, (_, label) in enumerate(choices, 1):
        console.print(Text(f"  {i}.  {label}", style="dim"))
    console.print()
    try:
        raw = input(f"  Choix (1–{len(choices)}) › ").strip()
        idx = int(raw) - 1
        if 0 <= idx < len(choices):
            return choices[idx][0]
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return choices[0][0]


def _run_raw_selector(choices: List[Tuple[str, str]], on_cancel: str = "reject") -> str:
    """Arrow-key selector using raw termios — no CPR needed."""
    import termios, tty

    BOLD_YELLOW = "\x1b[1;33m"
    DIM         = "\x1b[2m"
    RESET       = "\x1b[0m"
    UP          = "\x1b[{}A"

    idx = [0]
    first = [True]

    def render():
        if not first[0]:
            sys.stdout.write(UP.format(len(choices) + 1))
        first[0] = False
        lines = []
        for i, (_, label) in enumerate(choices):
            if i == idx[0]:
                lines.append(f"{BOLD_YELLOW}  ▶  {label}{RESET}\n")
            else:
                lines.append(f"{DIM}     {label}{RESET}\n")
        lines.append(f"{DIM}  ↑↓ · Entrée{RESET}\n")
        sys.stdout.write("".join(lines))
        sys.stdout.flush()

    def read_key() -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # Reads \x1b[A as 3 separate calls — rare fragmentation possible
                # if terminal buffers differently, but acceptable for a first impl.
                nxt = sys.stdin.read(1)
                if nxt == "[":
                    arrow = sys.stdin.read(1)
                    if arrow == "A": return "up"
                    if arrow == "B": return "down"
                return "escape"
            if ch in ("\r", "\n"): return "enter"
            if ch == "\x03":       return "ctrl_c"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    render()
    while True:
        key = read_key()
        if key == "down":
            idx[0] = (idx[0] + 1) % len(choices)
            render()
        elif key == "up":
            idx[0] = (idx[0] - 1) % len(choices)
            render()
        elif key == "enter":
            return choices[idx[0]][0]
        elif key in ("escape", "ctrl_c"):
            return on_cancel

_CHOICES: List[Tuple[str, str]] = [
    ("apply",  "✓  Appliquer"),
    ("reject", "✗  Refuser"),
    ("refine", "~  Préciser"),
]

_PLAN_CHOICES: List[Tuple[str, str]] = [
    ("accept", "✓  Accepter — procéder aux changements"),
    ("refine", "~  Préciser — ajouter des spécifications"),
    ("reject", "✗  Refuser — annuler ce plan"),
]

_EMAIL_CHOICES: List[Tuple[str, str]] = [
    ("send",   "✉  Envoyer"),
    ("cancel", "✗  Annuler"),
    ("modify", "~  Modifier"),
]

_MAX_DIFF_LINES = 60


# ── Diff renderer ─────────────────────────────────────────────────────────────

def _render_diff(change: FileChange) -> None:
    """Renders a colored diff for a single FileChange using Rich."""
    p = Path(change.path)
    is_new = not bool(change.original)

    # File header
    t = Text()
    t.append("  ")
    if is_new:
        t.append("+ nouveau  ", style="bold green")
    else:
        t.append("~ modifier  ", style=f"bold {ACCENT}")
    t.append(str(p), style=f"bold {ACCENT}")
    t.append(f"  —  {change.description}", style="dim")
    console.print(t)
    console.print()

    if is_new:
        lines = change.proposed.splitlines()
        for line in lines[:_MAX_DIFF_LINES]:
            console.print(Text(f"  + {line}", style="green"))
        if len(lines) > _MAX_DIFF_LINES:
            console.print(Text(f"  … ({len(lines) - _MAX_DIFF_LINES} lignes supplémentaires)", style="dim"))
    else:
        orig_lines = change.original.splitlines(keepends=True)
        new_lines  = change.proposed.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            orig_lines, new_lines,
            fromfile=f"a/{p.name}",
            tofile=f"b/{p.name}",
            n=3,
        ))
        shown = 0
        for raw_line in diff:
            if shown >= _MAX_DIFF_LINES:
                console.print(Text("  … (diff tronqué)", style="dim"))
                break
            line = raw_line.rstrip("\n")
            if line.startswith("+++") or line.startswith("---"):
                continue
            elif line.startswith("@@"):
                console.print(Text(f"  {line}", style="dim cyan"))
            elif line.startswith("+"):
                console.print(Text(f"  {line}", style="green"))
            elif line.startswith("-"):
                console.print(Text(f"  {line}", style="red"))
            else:
                console.print(Text(f"  {line}", style="dim"))
            shown += 1

    console.print()


# ── Arrow-key selector ────────────────────────────────────────────────────────

def _run_selector() -> str:
    """Displays a vertical 3-option selector. Returns 'apply', 'reject', or 'refine'."""
    if not _supports_raw_tty():
        return _fallback_selector(_CHOICES)
    return _run_raw_selector(_CHOICES, on_cancel="reject")


def _ask_refinement() -> str | None:
    """Inline text prompt for refinement instructions."""
    if not _supports_raw_tty():
        try:
            text = input("  préciser › ").strip()
            return text if text else None
        except (EOFError, KeyboardInterrupt):
            return None

    from prompt_toolkit import PromptSession
    from prompt_toolkit.styles import Style as PtStyle

    session = PromptSession(
        style=PtStyle.from_dict({"prompt": f"bold {_ACCENT_PT}"}),
    )
    try:
        text = session.prompt("  préciser › ").strip()
        return text if text else None
    except (EOFError, KeyboardInterrupt):
        return None


# ── Single-file review (ask mode) ─────────────────────────────────────────────

def review_single_latest() -> Tuple[str, str | None]:
    """
    Reviews the most recently proposed file change immediately (per-file HITL).
    Pops the latest change from pending_changes, shows its diff, and asks for approval.

    Returns:
        ("apply",  None)       — approved and written to disk
        ("reject", None)       — skipped
        ("refine", "<text>")   — user wants adjustments
    """
    change = pending_changes.pop_latest()
    if change is None:
        return ("reject", None)

    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    _render_diff(change)
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    choice = _run_selector()
    console.print()

    if choice == "apply":
        try:
            from src.agents.coding.pending import snapshots
            from src.infra.tools_cache import session_cache
            p = Path(change.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            snapshots.save(change.path, change.original)  # save before overwriting
            p.write_text(change.proposed, encoding="utf-8")
            session_cache.invalidate_filesystem()
            t = Text()
            t.append("  ✓  ", style="bold green")
            t.append(str(p), style="dim")
            console.print(t)
        except Exception as e:
            console.print(Text(f"  ✗  {change.path}: {e}", style="red"))
        return ("apply", None)

    if choice == "reject":
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("ignoré", style="dim")
        console.print(t)
        return ("reject", None)

    # refine
    refinement = _ask_refinement()
    if not refinement:
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("annulé", style="dim")
        console.print(t)
        return ("reject", None)
    return ("refine", refinement)


def auto_write_all(console_override=None) -> None:
    """Writes all pending changes to disk without asking (auto mode)."""
    _console = console_override or console
    changes = pending_changes.pop_all()
    if not changes:
        return

    from src.agents.coding.pending import snapshots
    from src.infra.tools_cache import session_cache
    applied, errors = [], []
    for change in changes:
        try:
            p = Path(change.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            snapshots.save(change.path, change.original)
            p.write_text(change.proposed, encoding="utf-8")
            applied.append(change.path)
        except Exception as e:
            errors.append(f"{change.path}: {e}")

    if applied:
        session_cache.invalidate_filesystem()
        t = Text()
        t.append("  ✓  ", style="bold green")
        t.append(
            f"{len(applied)} fichier{'s' if len(applied) > 1 else ''} écrit{'s' if len(applied) > 1 else ''} automatiquement",
            style=ACCENT,
        )
        _console.print(t)
        for path in applied:
            _console.print(Text(f"     {path}", style="dim"))
    for err in errors:
        _console.print(Text(f"  ✗  {err}", style="red"))


# ── Email review (HITL) ───────────────────────────────────────────────────────

def review_email() -> Tuple[str, str | None]:
    """
    Displays the pending email draft in Axon's visual style and asks for confirmation.

    Returns:
        ("send",   None)        — user approved, caller should call _do_send()
        ("cancel", None)        — user cancelled, draft cleared
        ("modify", "<text>")    — user wants changes, refinement text returned
    """
    from src.agents.gmail.tools import _draft

    if not _draft.get("has_draft"):
        return ("cancel", None)

    from rich.panel import Panel as _Panel
    from rich.table import Table
    from rich import box as rbox
    from rich.console import Group as _Group

    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    # Header
    t = Text()
    t.append("  ✉  ", style=f"bold {ACCENT}")
    t.append("email en attente d'envoi", style=f"bold {ACCENT}")
    console.print(t)
    console.print()

    # Meta fields (To / Subject)
    tbl = Table(box=rbox.SIMPLE_HEAD, show_header=False, padding=(0, 1))
    tbl.add_column("", style=f"bold {ACCENT}", no_wrap=True, width=7)
    tbl.add_column("", style="white")
    tbl.add_row("À", _draft["to"] or "")
    tbl.add_row("Objet", _draft["subject"] or "")

    body_text = Text(_draft["body"] or "", style="white")

    console.print(_Panel(
        _Group(tbl, Text(""), body_text),
        box=_BOX,
        border_style=f"dim {ACCENT}",
        title="[dim]brouillon[/dim]",
        title_align="left",
        padding=(1, 2),
    ))
    console.print()
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    # Selector
    if not _supports_raw_tty():
        choice = _fallback_selector(_EMAIL_CHOICES)
    else:
        choice = _run_raw_selector(_EMAIL_CHOICES, on_cancel="cancel")

    console.print()

    if choice not in ("send", "cancel", "modify"):
        # app.run() returned None ou valeur inattendue → annulation safe
        choice = "cancel"

    if choice == "send":
        from src.agents.gmail.tools import _do_send
        result = _do_send()
        t = Text()
        t.append("  ✉  ", style="bold green")
        t.append(result, style="dim")
        console.print(t)
        return ("send", None)

    if choice == "cancel":
        from src.agents.gmail.tools import _draft as d
        d.update({"to": None, "subject": None, "body": None, "has_draft": False})
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("envoi annulé", style="dim")
        console.print(t)
        return ("cancel", None)

    # modify
    refinement = _ask_refinement()
    if not refinement:
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("annulé", style="dim")
        console.print(t)
        return ("cancel", None)
    return ("modify", refinement)


# ── Notebook cell review (HITL) ───────────────────────────────────────────────

def _render_cell_diff(change: CellChange) -> None:
    """Renders a colored diff for a single cell change."""
    p = Path(change.path)
    is_new = change.cell_index < 0

    t = Text()
    t.append("  ")
    if is_new:
        t.append("+ nouvelle cellule  ", style="bold green")
        t.append(f"{p.name}", style=f"bold {ACCENT}")
        t.append(f"  après index {change.insert_after}", style="dim")
    else:
        t.append("~ cellule  ", style=f"bold {ACCENT}")
        t.append(f"{p.name}[{change.cell_index}]", style=f"bold {ACCENT}")
        t.append(f"  ({change.cell_type})", style="dim")
    console.print(t)
    console.print()

    if is_new:
        lines = change.proposed_source.splitlines()
        for line in lines[:_MAX_DIFF_LINES]:
            console.print(Text(f"  + {line}", style="green"))
        if len(lines) > _MAX_DIFF_LINES:
            console.print(Text(f"  … ({len(lines) - _MAX_DIFF_LINES} lignes supplémentaires)", style="dim"))
    else:
        orig_lines = change.original_source.splitlines(keepends=True)
        new_lines  = change.proposed_source.splitlines(keepends=True)
        diff = list(difflib.unified_diff(orig_lines, new_lines, fromfile="original", tofile="nouveau", n=3))
        shown = 0
        for raw_line in diff:
            if shown >= _MAX_DIFF_LINES:
                console.print(Text("  … (diff tronqué)", style="dim"))
                break
            line = raw_line.rstrip("\n")
            if line.startswith("+++") or line.startswith("---"):
                continue
            elif line.startswith("@@"):
                console.print(Text(f"  {line}", style="dim cyan"))
            elif line.startswith("+"):
                console.print(Text(f"  {line}", style="green"))
            elif line.startswith("-"):
                console.print(Text(f"  {line}", style="red"))
            else:
                console.print(Text(f"  {line}", style="dim"))
            shown += 1

    console.print()


def review_latest_cell_change() -> Tuple[str, str | None]:
    """
    HITL review for a single notebook cell change.
    Returns ("apply", None), ("reject", None), or ("refine", "<text>").
    """
    change = pending_cell_changes.pop_latest()
    if change is None:
        return ("reject", None)

    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    _render_cell_diff(change)
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    choice = _run_selector()
    console.print()

    if choice == "apply":
        try:
            from src.infra.tools_cache import session_cache
            apply_cell_change(change)
            session_cache.invalidate_filesystem()
            t = Text()
            t.append("  ✓  ", style="bold green")
            t.append(f"{change.path}[{change.cell_index}]" if change.cell_index >= 0 else f"{change.path} (nouvelle cellule)", style="dim")
            console.print(t)
        except Exception as e:
            console.print(Text(f"  ✗  {e}", style="red"))
        return ("apply", None)

    if choice == "reject":
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("ignoré", style="dim")
        console.print(t)
        return ("reject", None)

    refinement = _ask_refinement()
    if not refinement:
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("annulé", style="dim")
        console.print(t)
        return ("reject", None)
    return ("refine", refinement)

# ── Public entry point ────────────────────────────────────────────────────────

def review_pending() -> Tuple[str, str | None]:
    """
    Displays all pending proposed changes, lets the user navigate with ←→ and Enter.

    Returns:
        ("apply",  None)           — user approved, changes have been written
        ("reject", None)           — user refused, pending store cleared
        ("refine", "<text>")       — user wants adjustments, pending store cleared
    """
    changes = pending_changes.items
    if not changes:
        return ("reject", None)

    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    # Header
    n = len(changes)
    t = Text()
    t.append("  ")
    t.append(
        f"{n} modification{'s' if n > 1 else ''} proposée{'s' if n > 1 else ''}",
        style=f"bold {ACCENT}",
    )
    console.print(t)
    console.print()

    # Diffs
    for change in changes:
        _render_diff(change)

    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    choice = _run_selector()
    console.print()

    if choice == "apply":
        from src.agents.coding.pending import snapshots
        from src.infra.tools_cache import session_cache
        applied, errors = [], []
        for change in pending_changes.pop_all():
            try:
                p = Path(change.path)
                p.parent.mkdir(parents=True, exist_ok=True)
                snapshots.save(change.path, change.original)
                p.write_text(change.proposed, encoding="utf-8")
                applied.append(change.path)
            except Exception as e:
                errors.append(f"{change.path}: {e}")
        if applied:
            session_cache.invalidate_filesystem()

        t = Text()
        t.append("  ✓  ", style="bold green")
        t.append(
            f"{len(applied)} fichier{'s' if len(applied) > 1 else ''} écrit{'s' if len(applied) > 1 else ''}",
            style=ACCENT,
        )
        console.print(t)
        for path in applied:
            console.print(Text(f"     {path}", style="dim"))
        for err in errors:
            console.print(Text(f"  ✗  {err}", style="red"))
        return ("apply", None)

    if choice == "reject":
        pending_changes.clear()
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("modifications refusées", style="dim")
        console.print(t)
        return ("reject", None)

    # refine
    pending_changes.clear()
    refinement = _ask_refinement()
    if not refinement:
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("annulé", style="dim")
        console.print(t)
        return ("reject", None)

    return ("refine", refinement)


# ── Plan review (HITL) ────────────────────────────────────────────────────────

def _run_plan_selector() -> str:
    """3-option arrow-key selector for plan review. Returns 'accept', 'refine', or 'reject'."""
    if not _supports_raw_tty():
        return _fallback_selector(_PLAN_CHOICES)
    return _run_raw_selector(_PLAN_CHOICES, on_cancel="reject")


def review_plan() -> Tuple[str, str | None]:
    """
    HITL selector displayed after an <axon:plan> block is rendered.

    Returns:
        ("accept", None)       — plan approved, caller should disable plan mode and execute
        ("refine", "<text>")   — user wants the plan revised with these specs
        ("reject", None)       — plan discarded
    """
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    choice = _run_plan_selector()
    console.print()

    if choice == "accept":
        t = Text()
        t.append("  ✓  ", style="bold green")
        t.append("plan accepté — exécution en cours…", style="dim")
        console.print(t)
        return ("accept", None)

    if choice == "reject":
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("plan refusé", style="dim")
        console.print(t)
        return ("reject", None)

    # refine
    refinement = _ask_refinement()
    if not refinement:
        t = Text()
        t.append("  ✗  ", style="bold red")
        t.append("annulé", style="dim")
        console.print(t)
        return ("reject", None)

    t = Text()
    t.append("  ~  ", style=f"bold {ACCENT}")
    t.append("révision du plan en cours…", style="dim")
    console.print(t)
    return ("refine", refinement)
