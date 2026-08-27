"""Shared in-memory stores for coding agent state (HITL review + plan tracking)."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import List

# Tools that count as "analysis" proof (read-only, no disk writes)
_ANALYSIS_TOOLS: frozenset[str] = frozenset({
    "notebook_read", "local_read_file", "local_grep", "local_glob",
    "local_find_file", "local_list_directory", "shell_ls", "shell_pwd",
    "git_status", "git_log", "git_diff", "find_git_repos",
    "web_research_report", "web_search_news", "url_fetch", "dev_explain",
})

# Outils dont une acceptation vaut « ce chemin a été écrit sur le disque ».
_WRITE_TOOLS: frozenset[str] = frozenset({
    "propose_file_change", "edit_file", "notebook_insert_cell",
})


class RecentToolsStore:
    """Tracks tool outcomes since the last dev_plan_step_done for real proof validation."""

    def __init__(self) -> None:
        self._called: set[str] = set()
        self._written_paths: set[str] = set()           # files written to disk
        self._edited_cells: set[tuple[str, int]] = set() # (path, cell_index) notebook edits
        self._shell_ok: bool = False                     # any shell_run with exit_code 0

    def record(self, tool_name: str, args: dict, result: object) -> None:
        self._called.add(tool_name)

        if isinstance(result, dict):
            status = result.get("status", "")
            path = (args or {}).get("path", "")

            # File accepted (HITL or auto)
            if tool_name in _WRITE_TOOLS and status == "accepted" and path:
                self._written_paths.add(path)

            # Notebook cell accepted
            if tool_name == "notebook_edit_cell" and status == "accepted" and path:
                self._written_paths.add(path)
                cell_idx = (args or {}).get("cell_index", -1)
                if cell_idx >= 0:
                    self._edited_cells.add((path, cell_idx))

            # Shell success
            if tool_name == "shell_run" and result.get("exit_code", 1) == 0:
                self._shell_ok = True

    def any_analysis(self) -> bool:
        return bool(self._called & _ANALYSIS_TOOLS)

    def file_was_written(self, path: str) -> bool:
        return path in self._written_paths

    def cell_was_edited(self, path: str, cell_index: int) -> bool:
        return (path, cell_index) in self._edited_cells

    def shell_succeeded(self) -> bool:
        return self._shell_ok

    def clear(self) -> None:
        self._called.clear()
        self._written_paths.clear()
        self._edited_cells.clear()
        self._shell_ok = False


recent_tools = RecentToolsStore()


@dataclass
class FileChange:
    path: str
    original: str     
    proposed: str
    description: str
    # Supprimer passe par la MÊME revue qu'écrire. L'agent de code n'avait aucun
    # outil capable d'effacer un fichier : sa seule voie était `rm` via
    # `shell_run`, refusée comme destructive — et aucune confirmation ne peut
    # être demandée depuis sa boucle, qui n'a pas de graphe. « supprime x.py »
    # y était donc structurellement impossible.
    supprime: bool = field(default=False)


def appliquer(change: FileChange) -> None:
    """Écrit ou efface, après avoir gardé de quoi défaire.

    Le même bloc était recopié aux trois endroits qui appliquent une revue ; une
    suppression y aurait fait un quatrième oubli possible.
    """
    from pathlib import Path as _Path

    cible = _Path(change.path)
    snapshots.save(change.path, change.original)
    if change.supprime:
        cible.unlink(missing_ok=True)
        return
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(change.proposed, encoding="utf-8")


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
    """Le plan du specialist, et le fait qu'il en exige un.

    `exige_un_plan` distingue « le specialist n'a pas encore planifié » de « ce
    n'est pas le specialist qui appelle ». Sans cette distinction, la garde de
    `propose_file_change` s'appliquait aussi à l'orchestrateur, qui n'a pas de
    `dev_plan_create` : `shell_run` refusait `>` en renvoyant vers
    `propose_file_change`, `edit_file` refusait un fichier absent en renvoyant
    vers `propose_file_change`, et `propose_file_change` réclamait un plan que
    rien ne pouvait créer. Créer un fichier depuis l'orchestrateur était donc
    impossible par le chemin que les messages d'erreur désignaient.
    """

    def __init__(self) -> None:
        self._steps: List[PlanStep] = []
        self.exige_un_plan = False

    def create(self, steps: List[str]) -> None:
        self._steps = [PlanStep(label=s) for s in steps]

    def replace(self, steps: List[str], done_count: int) -> None:
        """Réécrit le plan en gardant cochées les `done_count` premières étapes."""
        self._steps = [PlanStep(label=s, done=i < done_count) for i, s in enumerate(steps)]

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

    @contextmanager
    def run_specialist(self):
        """Le temps d'un run du specialist, écrire exige d'avoir planifié."""
        precedent = self.exige_un_plan
        self.exige_un_plan = True
        try:
            yield
        finally:
            self.exige_un_plan = precedent

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


# ── Snapshot store (undo support) ─────────────────────────────────────────────

class SnapshotStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}  # path → content before last write

    def save(self, path: str, content: str) -> None:
        if path not in self._data:  # keep the oldest snapshot (true original)
            self._data[path] = content

    def restore(self, path: str) -> bool:
        if path not in self._data:
            return False
        from pathlib import Path
        Path(path).write_text(self._data.pop(path), encoding="utf-8")
        return True

    def restore_all(self) -> list[str]:
        restored = []
        for path, content in list(self._data.items()):
            try:
                from pathlib import Path
                Path(path).write_text(content, encoding="utf-8")
                restored.append(path)
            except Exception:
                pass
        self._data.clear()
        return restored

    def clear(self) -> None:
        self._data.clear()

    def __bool__(self) -> bool:
        return bool(self._data)

    @property
    def paths(self) -> list[str]:
        return list(self._data.keys())


snapshots = SnapshotStore()


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


def reset_specialist_state() -> None:
    """Réinitialise tous les singletons module-level entre les phases /build.
    La liste messages dans _run() est déjà locale — aucun LangGraph thread impliqué."""
    dev_plan.clear()
    recent_tools.clear()
    pending_changes.clear()
    snapshots.clear()
    try:
        from src.infra.tools_cache import session_cache
        # Invalide uniquement les caches filesystem/git (potentiellement périmés entre phases).
        # Les résultats de recherche web (TTL 300s) sont préservés : pas besoin de les refaire.
        # Les fichiers modifiés pendant la phase sont déjà invalidés par on_tool_executed()
        # au moment de chaque propose_file_change — aucun risque de lire un fichier périmé.
        session_cache.invalidate_filesystem()
    except Exception:
        pass
