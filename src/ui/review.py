"""HITL review UI — shows diffs, arrow-key navigation to approve/reject/refine."""
from __future__ import annotations

import difflib
import os
import sys
from pathlib import Path
from typing import List, Tuple

from rich.console import Console
from rich.panel import Panel
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
        ("reject", None)       — l'utilisateur a REELLEMENT refusé
        ("refine", "<text>")   — user wants adjustments
        ("nothing", None)      — rien à relire : personne n'a rien décidé
    """
    change = pending_changes.pop_latest()
    if change is None:
        # Jamais ("reject") ici : l'utilisateur n'a rien vu, donc rien refusé.
        return ("nothing", None)

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
    Returns ("apply", None), ("reject", None), ("refine", "<text>")
    ou ("nothing", None) quand il n'y a rien à relire.
    """
    change = pending_cell_changes.pop_latest()
    if change is None:
        # Jamais ("reject") ici : l'utilisateur n'a rien vu, donc rien refusé.
        return ("nothing", None)

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


# ── Clarification questionnaire ───────────────────────────────────────────────

def _prompt_input(label: str) -> str:
    """Single-line prompt via prompt_toolkit, fallback to input()."""
    if _supports_raw_tty():
        from prompt_toolkit import PromptSession
        from prompt_toolkit.styles import Style as PtStyle
        try:
            session = PromptSession(style=PtStyle.from_dict({"prompt": f"bold {_ACCENT_PT}"}))
            return session.prompt(label).strip()
        except (EOFError, KeyboardInterrupt):
            return ""
    try:
        return input(label).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def _ask_with_choices(question: str, choices: list[str], q_num: int, total: int) -> str:
    """Arrow-key picker for one question. Appends 'Autre (préciser)' automatically."""
    AUTRE = "Autre (préciser)"
    # Le modèle ajoute parfois lui-même « Autre (préciser) » malgré la consigne du tool ;
    # sans dédoublonnage l'option apparaissait DEUX fois dans le sélecteur.
    _norm = lambda c: str(c).strip().casefold().rstrip(".")
    all_choices = [c for c in choices if _norm(c) != _norm(AUTRE)] + [AUTRE]
    raw: List[Tuple[str, str]] = [(c, c) for c in all_choices]

    t = Text()
    t.append(f"  {q_num}/{total}  ", style=f"dim {ACCENT}")
    t.append(question, style="bold")
    console.print(t)
    console.print()

    if _supports_raw_tty():
        selected = _run_raw_selector(raw, on_cancel=AUTRE)
    else:
        selected = _fallback_selector(raw)

    if selected == AUTRE:
        console.print()
        val = _prompt_input("  préciser › ")
        t2 = Text()
        t2.append("  ✓  ", style="bold green")
        t2.append(val or "—", style="dim")
        console.print(t2)
        console.print()
        return val

    t2 = Text()
    t2.append("  ✓  ", style="bold green")
    t2.append(selected, style="dim")
    console.print(t2)
    console.print()
    return selected


def ask_user_questions(questions: list) -> dict:
    """Shows a questionnaire. Each item is a str or {"question": "...", "choices": [...]}.
    Returns {question: answer, ...}."""
    answers: dict[str, str] = {}
    total = len(questions)

    console.print()
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    t = Text()
    t.append("  ")
    t.append("Question" if total == 1 else "Questions", style=f"bold {ACCENT}")
    t.append(f"  ({total})", style=f"dim {ACCENT}")
    console.print(t)
    console.print()

    for i, q in enumerate(questions, 1):
        if isinstance(q, dict):
            text = q.get("question", str(q))
            choices = q.get("choices", [])
        else:
            text = str(q)
            choices = []

        if choices:
            answer = _ask_with_choices(text, choices, i, total)
        else:
            t2 = Text()
            t2.append(f"  {i}/{total}  ", style=f"dim {ACCENT}")
            t2.append(text, style="bold")
            console.print(t2)
            console.print()
            answer = _prompt_input("  › ")
            t3 = Text()
            t3.append("  ✓  ", style="bold green")
            t3.append(answer or "—", style="dim")
            console.print(t3)
            console.print()

        answers[text] = answer

    console.print()
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    console.print()
    return answers


def _servir_plan(demande) -> list[str]:
    """Affiche le plan et collecte la décision."""
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    console.print(Panel(
        Text(demande.apercu), box=_BOX, border_style=f"dim {ACCENT}",
        title="[dim]plan proposé[/dim]", title_align="left", padding=(1, 2)))
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    choix = _run_plan_selector()
    console.print()
    if choix == "accept":
        return ["Exécuter le plan", ""]
    if choix == "refine":
        return ["Préciser", _ask_refinement() or ""]
    return ["Abandonner", ""]


def _servir_envoi(demande) -> list[str]:
    """Affiche le brouillon et collecte la décision, sans envoyer.

    L'envoi est fait par le nœud `envoi`, pas par le client.
    """
    from rich import box as rbox
    from rich.console import Group as _Group
    from rich.table import Table

    champs = demande.extra or {}
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    entete = Text()
    entete.append("  ✉  ", style=f"bold {ACCENT}")
    entete.append("email en attente d'envoi", style=f"bold {ACCENT}")
    console.print(entete)
    console.print()

    tbl = Table(box=rbox.SIMPLE_HEAD, show_header=False, padding=(0, 1))
    tbl.add_column("", style=f"bold {ACCENT}", no_wrap=True, width=7)
    tbl.add_column("", style="white")
    tbl.add_row("À", champs.get("to") or "")
    tbl.add_row("Objet", champs.get("subject") or "")

    console.print(Panel(
        _Group(tbl, Text(""), Text(champs.get("body") or "", style="white")),
        box=_BOX, border_style=f"dim {ACCENT}",
        title="[dim]brouillon[/dim]", title_align="left", padding=(1, 2),
    ))
    console.print()
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    if not _supports_raw_tty():
        choix = _fallback_selector(_EMAIL_CHOICES)
    else:
        choix = _run_raw_selector(_EMAIL_CHOICES, on_cancel="cancel")
    console.print()

    # Une valeur inattendue vaut annulation : un mail parti par accident ne se
    # rattrape pas, une annulation de trop se refait.
    if choix == "send":
        return ["Envoyer", ""]
    if choix == "modify":
        return ["Modifier", _ask_refinement() or ""]
    return ["Annuler", ""]


def _servir_diff(demande) -> list[str]:
    """Affiche les diffs et collecte la décision.

    Utilise `Demande.extra`, qui porte les changements complets — l'aperçu texte
    du protocole est destiné aux clients sans rendu de diff.
    """
    from src.agents.coding.pending import FileChange

    changements = [
        FileChange(path=c.get("path", ""), original=c.get("original", ""),
                   proposed=c.get("proposed", ""), description=c.get("description", ""))
        for c in (demande.extra.get("changements") or [])
    ]
    cellules = [
        CellChange(path=c.get("path", ""), cell_index=c.get("cell_index", -1),
                   insert_after=c.get("insert_after", -1),
                   cell_type=c.get("cell_type", "code"),
                   original_source=c.get("original_source", ""),
                   proposed_source=c.get("proposed_source", ""),
                   description=c.get("description", ""))
        for c in (demande.extra.get("cellules") or [])
    ]
    if not changements and not cellules:
        return ["", ""]

    console.print(Rule(characters="·", style=f"dim {ACCENT}"))
    nombre = len(changements) + len(cellules)
    entete = Text()
    entete.append("  ")
    entete.append(f"{nombre} modification{'s' if nombre > 1 else ''} proposée"
                  f"{'s' if nombre > 1 else ''}", style=f"bold {ACCENT}")
    console.print(entete)
    console.print()
    for changement in changements:
        _render_diff(changement)
    # Rendu dédié : afficher une cellule comme un fichier perdrait son index et
    # son type.
    for cellule in cellules:
        _render_cell_diff(cellule)
    console.print(Rule(characters="·", style=f"dim {ACCENT}"))

    choix = _run_selector()          # "apply" | "reject" | "refine"
    if choix == "apply":
        return ["Appliquer", ""]
    if choix == "refine":
        return ["Préciser", _ask_refinement() or ""]
    return ["Refuser", ""]


def servir_demande(demande) -> list[str]:
    """Affiche une `Demande` et rend une réponse par question, dans l'ordre.

    Le seul point où le TUI répond à une interruption du graphe. Le rendu dépend
    du genre ; le client ne fait que montrer et rendre des chaînes.
    """
    if demande.genre == "diff":
        return _servir_diff(demande)

    if demande.genre == "envoi":
        return _servir_envoi(demande)

    if demande.genre == "plan":
        return _servir_plan(demande)

    if demande.apercu.strip():
        console.print()
        console.print(Panel(
            Text(demande.apercu),
            border_style=f"dim {ACCENT}",
            title="[dim]à vérifier avant de répondre[/dim]",
            title_align="left",
            padding=(0, 2),
        ))

    posees = [{"question": q.texte, "choices": list(q.choix)} for q in demande.questions]
    try:
        reponses = ask_user_questions(posees)
    except Exception as erreur:
        console.print(Text(f"  erreur questionnaire : {erreur}", style="red"))
        # Une panne d'affichage ne vaut pas accord : `hitl.accorde` lit le vide
        # comme un refus.
        return ["" for _ in demande.questions]

    # `ask_user_questions` rend un dict indexé par le texte ; le graphe attend
    # l'ordre. Une réponse absente rend "", jamais une valeur par défaut.
    return [reponses.get(q.texte, "") for q in demande.questions]
