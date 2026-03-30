"""HITL review UI — shows diffs, arrow-key navigation to approve/reject/refine."""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import List, Tuple

from prompt_toolkit import Application
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from src.agents.coding.pending import FileChange, pending_changes
from .panels import ACCENT, _BOX, _BORDER

console = Console()

_ACCENT_PT = "ansiyellow"   # prompt_toolkit equivalent of Rich's color(214)

_PT_STYLE = Style.from_dict({
    "selected": f"bold {_ACCENT_PT}",
    "normal":   "ansibrightblack",
    "hint":     f"dim {_ACCENT_PT}",
})

_CHOICES: List[Tuple[str, str]] = [
    ("apply",  "✓  Appliquer"),
    ("reject", "✗  Refuser"),
    ("refine", "~  Préciser"),
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
    idx = [0]

    def get_tokens():
        parts: list = []
        for i, (key, label) in enumerate(_CHOICES):
            if i == idx[0]:
                parts.append(("class:selected", f"  ▶  {label}\n"))
            else:
                parts.append(("class:normal",   f"     {label}\n"))
        parts.append(("class:hint", "  ↑↓ · Entrée"))
        return parts

    kb = KeyBindings()

    @kb.add("down")
    @kb.add("tab")
    def _fwd(event):
        idx[0] = (idx[0] + 1) % len(_CHOICES)

    @kb.add("up")
    @kb.add("s-tab")
    def _bwd(event):
        idx[0] = (idx[0] - 1) % len(_CHOICES)

    @kb.add("enter")
    def _ok(event):
        event.app.exit(result=_CHOICES[idx[0]][0])

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event):
        event.app.exit(result="reject")

    app = Application(
        layout=Layout(
            Window(
                FormattedTextControl(get_tokens, focusable=True),
                height=len(_CHOICES) + 1,
            )
        ),
        key_bindings=kb,
        style=_PT_STYLE,
        full_screen=False,
        mouse_support=False,
    )
    return app.run()


def _ask_refinement() -> str | None:
    """Inline text prompt for refinement instructions."""
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
            p = Path(change.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(change.proposed, encoding="utf-8")
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

    applied, errors = [], []
    for change in changes:
        try:
            p = Path(change.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(change.proposed, encoding="utf-8")
            applied.append(change.path)
        except Exception as e:
            errors.append(f"{change.path}: {e}")

    if applied:
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
    idx = [0]
    choices = _EMAIL_CHOICES

    def get_tokens():
        parts: list = []
        for i, (key, label) in enumerate(choices):
            if i == idx[0]:
                parts.append(("class:selected", f"  ▶  {label}\n"))
            else:
                parts.append(("class:normal",   f"     {label}\n"))
        parts.append(("class:hint", "  ↑↓ · Entrée"))
        return parts

    kb = KeyBindings()

    @kb.add("down")
    @kb.add("tab")
    def _fwd(event):
        idx[0] = (idx[0] + 1) % len(choices)

    @kb.add("up")
    @kb.add("s-tab")
    def _bwd(event):
        idx[0] = (idx[0] - 1) % len(choices)

    @kb.add("enter")
    def _ok(event):
        event.app.exit(result=choices[idx[0]][0])

    @kb.add("escape")
    @kb.add("c-c")
    def _esc(event):
        event.app.exit(result="cancel")

    app = Application(
        layout=Layout(
            Window(
                FormattedTextControl(get_tokens, focusable=True),
                height=len(choices) + 1,
            )
        ),
        key_bindings=kb,
        style=_PT_STYLE,
        full_screen=False,
        mouse_support=False,
    )
    choice = app.run()
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
        applied, errors = [], []
        for change in pending_changes.pop_all():
            try:
                p = Path(change.path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(change.proposed, encoding="utf-8")
                applied.append(change.path)
            except Exception as e:
                errors.append(f"{change.path}: {e}")

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
