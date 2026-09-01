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
        self._deleted_paths: set[str] = set()           # files removed from disk
        self._edited_cells: set[tuple[str, int]] = set() # (path, cell_index) notebook edits
        self._shell_ok: bool = False                     # any shell_run with exit_code 0

    def note_ecriture(self, path: str, supprime: bool = False) -> None:
        """Appelé par `appliquer`, seul endroit du projet qui touche le disque.

        `record` déduisait l'écriture du statut rendu par l'outil, et attendait
        « accepted » — que `propose_file_change` ne rend JAMAIS en mode `ask` : il
        rend « proposed », la revue vient après. `file_was_written` était donc
        toujours faux, `dev_plan_step_done(proof_type="file_written")` toujours
        refusé, et le modèle, incapable de cocher l'étape qu'il venait pourtant
        d'accomplir, fabriquait une preuve recevable : `echo done`, `true`,
        `echo step1done` — vu en session. Le fait est constaté là où il a lieu.
        """
        self._written_paths.add(path)
        (self._deleted_paths.add if supprime else self._deleted_paths.discard)(path)

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

    def file_was_deleted(self, path: str) -> bool:
        return path in self._deleted_paths

    def note_cellule(self, path: str, cell_index: int) -> None:
        """Même correction que `note_ecriture`, pour les notebooks : en mode `ask`,
        `notebook_edit_cell` rend « proposed » et la revue vient après, si bien que
        `cell_was_edited` restait faux et l'étape incochable."""
        self._written_paths.add(path)
        if cell_index >= 0:
            self._edited_cells.add((path, cell_index))

    def cell_was_edited(self, path: str, cell_index: int) -> bool:
        return (path, cell_index) in self._edited_cells

    def shell_succeeded(self) -> bool:
        return self._shell_ok

    def clear(self) -> None:
        self._called.clear()
        self._written_paths.clear()
        self._deleted_paths.clear()
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
    # L'état d'avant se lit sur le DISQUE, pas dans `change.original` : celui-ci
    # vaut "" aussi bien pour un fichier neuf que pour un fichier vide.
    snapshots.save(change.path, change.original if cible.exists() else None)
    if change.supprime:
        cible.unlink(missing_ok=True)
    else:
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(change.proposed, encoding="utf-8")
    recent_tools.note_ecriture(change.path, supprime=change.supprime)


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
        self._tache = ""       # la demande en cours, pour ne repartir qu'une fois

    def create(self, steps: List[str]) -> None:
        self._steps = [PlanStep(label=s) for s in steps]

    def replace(self, steps: List[str], faits: set[str]) -> None:
        """Réécrit le plan en gardant cochées les étapes de `faits`, où qu'elles soient.

        C'était `done_count` : les cochées devaient être les N PREMIÈRES. Or rien
        n'oblige à finir dans l'ordre — cocher l'étape 2 avant la 1 est courant, et
        rendait alors toute révision impossible. Vécu : « plan révisé » affiché
        deux fois de suite sur un plan qui ne changeait pas, parce que l'appel
        était refusé à chaque tour.
        """
        self._steps = [PlanStep(label=s, done=s in faits) for s in steps]

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
    def run_specialist(self, tache: str = ""):
        """Le temps d'un run du specialist, écrire exige d'avoir planifié.

        Le plan repart à zéro à chaque DEMANDE — pas à chaque entrée. C'est un
        singleton de module, que seul `/build` réinitialisait : une deuxième
        demande dans la même session héritait du plan de la première, et
        `dev_plan_create` répondait « already_exists, continue avec les étapes
        existantes ».

        Mais le nœud `coder` ré-entre ici après CHAQUE interruption — un plan
        soumis, un diff relu — et effacer à l'entrée vidait le plan en plein
        milieu du travail. Le modèle le retrouvait disparu, le recréait
        (« Recréation du plan après écriture du fichier », vu en session), et le
        plan neuf rouvrait le questionnaire de validation. Mesuré : trois
        validations pour une seule demande.
        """
        precedent = self.exige_un_plan
        self.exige_un_plan = True
        if tache != self._tache:
            self._tache = tache
            self.clear()
            recent_tools.clear()
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
    """L'état d'avant, pour `/undo`.

    `None` veut dire « le fichier n'existait pas » — et une chaîne vide, « il
    existait, vide ». Les deux étaient stockés pareil : annuler une CRÉATION
    réécrivait donc le fichier à vide au lieu de l'effacer, et `/undo` laissait
    derrière lui exactement ce qu'il prétendait retirer.
    """

    def __init__(self) -> None:
        self._data: dict[str, str | None] = {}  # path → contenu d'avant, ou None

    def save(self, path: str, content: str | None) -> None:
        if path not in self._data:  # keep the oldest snapshot (true original)
            self._data[path] = content

    def _rendre(self, path: str, content: str | None) -> None:
        from pathlib import Path

        cible = Path(path)
        if content is None:
            cible.unlink(missing_ok=True)
            return
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(content, encoding="utf-8")

    def restore(self, path: str) -> bool:
        if path not in self._data:
            return False
        self._rendre(path, self._data.pop(path))
        return True

    def restore_all(self) -> list[str]:
        restored = []
        for path, content in list(self._data.items()):
            try:
                self._rendre(path, content)
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
