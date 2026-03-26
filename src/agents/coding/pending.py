"""Shared in-memory stores for coding agent state (HITL review + plan tracking)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class FileChange:
    path: str
    original: str       # empty string if new file
    proposed: str
    description: str


class PendingStore:
    def __init__(self) -> None:
        self._changes: List[FileChange] = []

    def add(self, change: FileChange) -> None:
        # Replace if same path proposed twice
        self._changes = [c for c in self._changes if c.path != change.path]
        self._changes.append(change)

    def clear(self) -> None:
        self._changes.clear()

    def pop_all(self) -> List[FileChange]:
        items = list(self._changes)
        self._changes.clear()
        return items

    def pop_latest(self) -> "FileChange | None":
        if not self._changes:
            return None
        return self._changes.pop()

    def __bool__(self) -> bool:
        return bool(self._changes)

    def __len__(self) -> int:
        return len(self._changes)

    @property
    def items(self) -> List[FileChange]:
        return list(self._changes)


# Singleton shared between the LLM tools and the UI
pending_changes = PendingStore()


# ── Dev plan (todo list) ──────────────────────────────────────────────────────

@dataclass
class PlanStep:
    label: str
    done: bool = field(default=False)


class DevPlanStore:
    def __init__(self) -> None:
        self._steps: List[PlanStep] = []

    def create(self, steps: List[str]) -> None:
        self._steps = [PlanStep(label=s) for s in steps]

    def check(self, index: int) -> bool:
        """Mark step at index as done. Returns False if already done or out of range."""
        if 0 <= index < len(self._steps):
            if self._steps[index].done:
                return False  # already done, no change
            self._steps[index].done = True
            return True
        return False

    def clear(self) -> None:
        self._steps.clear()

    def __bool__(self) -> bool:
        return bool(self._steps)

    @property
    def steps(self) -> List[PlanStep]:
        return list(self._steps)

    @property
    def next_pending_index(self) -> int | None:
        for i, s in enumerate(self._steps):
            if not s.done:
                return i
        return None


dev_plan = DevPlanStore()


def render_plan(console) -> None:
    """Renders the current dev plan state. Pass any Rich Console instance."""
    from rich.rule import Rule
    from rich.text import Text

    steps = dev_plan.steps
    if not steps:
        return

    _ACCENT = "color(214)"
    console.print(Rule("  plan  ", characters="·", style=f"dim {_ACCENT}"))
    next_idx = dev_plan.next_pending_index

    for i, step in enumerate(steps):
        t = Text()
        if step.done:
            t.append("  ✓  ", style="bold green")
            t.append(step.label, style="dim")
        elif i == next_idx:
            t.append("  ●  ", style=f"bold {_ACCENT}")
            t.append(step.label, style=_ACCENT)
        else:
            t.append("  ○  ", style="dim")
            t.append(step.label, style="dim")
        console.print(t)

    console.print(Rule(characters="·", style=f"dim {_ACCENT}"))
