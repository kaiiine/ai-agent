"""Boot loader — percentage progress bar, Axon DA."""
from __future__ import annotations

import threading
import time
from typing import Callable

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.padding import Padding
from rich.text import Text

ACCENT = "color(214)"

# ── Global step callback ──────────────────────────────────────────────────────

_step_cb: Callable[[str], None] | None = None


def set_step_callback(fn: Callable[[str], None]) -> None:
    global _step_cb
    _step_cb = fn


def report_step(label: str) -> None:
    if _step_cb:
        _step_cb(label)


# ── Progress bar ──────────────────────────────────────────────────────────────

_BAR_W = 32
# Steps reported via report_step — used to compute target percentages.
_N_STEPS = 3  # modules → construction → index


def _build_bar(pct: float) -> Text:
    filled = int(_BAR_W * pct / 100)
    t = Text()
    t.append("█" * filled,         style=f"bold {ACCENT}")
    t.append("░" * (_BAR_W - filled), style=f"dim {ACCENT}")
    t.append(f"  {int(pct):>3}%",  style=f"bold {ACCENT}")
    return t


# ── BootLoader ────────────────────────────────────────────────────────────────

class BootLoader:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._step_idx: int = 0
        self._pct: float = 0.0
        self._target: float = 0.0
        self._label: str = "initialisation…"
        self._live: Live | None = None
        self._stopped = False
        self._lock = threading.Lock()

    def _target_for(self, idx: int) -> float:
        # 0 → 0 %, each step covers 95/N_STEPS %; 100 % on stop()
        return min(95.0, idx * (95.0 / _N_STEPS))

    def _render(self):
        h = max(self._console.height, 24)
        pad = max(0, h // 2 - 6)

        rows: list = []
        rows.append(Text(""))

        # ── title ──────────────────────────────────────────────────────────────
        title = Text()
        title.append("A  X  O  N", style=f"bold {ACCENT}")
        rows.append(Align.center(title))

        # ── thin rule ──────────────────────────────────────────────────────────
        rows.append(Text(""))
        sep = Text()
        sep.append("─" * (_BAR_W + 6), style=f"dim {ACCENT}")
        rows.append(Align.center(sep))
        rows.append(Text(""))

        # ── bar ────────────────────────────────────────────────────────────────
        with self._lock:
            pct = self._pct
            label = self._label
        rows.append(Align.center(_build_bar(pct)))
        rows.append(Text(""))

        # ── step label ─────────────────────────────────────────────────────────
        step = Text()
        step.append(label, style="dim")
        rows.append(Align.center(step))

        rows.append(Text(""))
        rows.append(Align.center(sep))

        return Padding(Group(*rows), (pad, 0, 0, 0))

    # ── Animation tick ────────────────────────────────────────────────────────

    def _tick(self) -> None:
        while not self._stopped:
            with self._lock:
                target = self._target
                pct = self._pct
            if pct < target:
                speed = max(0.8, (target - pct) * 0.12)
                with self._lock:
                    self._pct = min(target, pct + speed)
                if self._live:
                    self._live.update(self._render())
            time.sleep(0.04)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._stopped = False
        set_step_callback(self._advance)
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=25,
            screen=True,
        )
        self._live.start(refresh=True)
        t = threading.Thread(target=self._tick, daemon=True)
        t.start()

    def _advance(self, label: str) -> None:
        self._step_idx += 1
        with self._lock:
            self._label = label
            self._target = self._target_for(self._step_idx)

    def stop(self) -> None:
        self._stopped = True
        set_step_callback(None)
        if self._live:
            with self._lock:
                self._pct = 100.0
                self._label = "prêt"
            self._live.update(self._render())
            self._live.stop()
            self._live = None
