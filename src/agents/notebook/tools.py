"""Notebook tools — cell-level read/edit/insert/run for Jupyter notebooks."""
from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List

from langchain_core.tools import tool


# ── Cell change store (HITL) ──────────────────────────────────────────────────

@dataclass
class CellChange:
    path: str
    cell_index: int       # -1 = insert operation
    insert_after: int     # only meaningful when cell_index == -1
    cell_type: str        # "code" | "markdown"
    original_source: str  # "" for new cells
    proposed_source: str
    description: str


class PendingCellStore:
    def __init__(self) -> None:
        self._changes: list[CellChange] = []

    def add(self, change: CellChange) -> None:
        self._changes.append(change)

    def pop_latest(self) -> CellChange | None:
        return self._changes.pop() if self._changes else None

    @property
    def items(self) -> list[CellChange]:
        """Ce qui attend, sans le consommer.

        Le nœud de revue montre puis décide, et le graphe rejoue le nœud entre
        les deux : une lecture consommante ne trouverait plus rien au rejeu.
        """
        return list(self._changes)

    def pop_all(self) -> list[CellChange]:
        pris, self._changes = list(self._changes), []
        return pris

    def clear(self) -> None:
        self._changes.clear()

    def __bool__(self) -> bool:
        return bool(self._changes)


pending_cell_changes = PendingCellStore()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Notebook introuvable : {path}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, nb: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)


def _to_source_list(source: str) -> list[str]:
    """Convert a plain string to the ipynb source list format."""
    lines = source.split("\n")
    result = [line + "\n" for line in lines[:-1]]
    if lines[-1]:
        result.append(lines[-1])
    return result


def _make_cell(cell_type: str, source: str) -> dict:
    base = {
        "cell_type": cell_type,
        "id": uuid.uuid4().hex[:8],
        "metadata": {},
        "source": _to_source_list(source),
    }
    if cell_type == "code":
        base["execution_count"] = None
        base["outputs"] = []
    return base


# ── Apply helpers (called by review.py on user approval) ──────────────────────

def apply_cell_change(change: CellChange) -> None:
    """Write a CellChange to disk (called after user approval)."""
    nb = _load(change.path)
    cells = nb.setdefault("cells", [])

    if change.cell_index >= 0:
        # Edit existing cell
        cell = cells[change.cell_index]
        cell["source"] = _to_source_list(change.proposed_source)
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    else:
        # Insert new cell
        new_cell = _make_cell(change.cell_type, change.proposed_source)
        insert_at = change.insert_after + 1
        cells.insert(insert_at, new_cell)

    _save(change.path, nb)


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool("notebook_read")
def notebook_read(path: str) -> Dict[str, Any]:
    """
    Reads a Jupyter notebook and returns its cells with index, type, and full source.
    Always call this before editing a notebook to know which cells exist and their indices.

    Args:
        path: absolute path to the .ipynb file
    Returns:
        {"status": "ok", "n_cells": N, "cells": [{"index", "type", "source", "output_preview"}]}
    """
    try:
        nb = _load(path)
    except Exception as e:
        return {"status": "error", "error": str(e)}

    result_cells = []
    for i, cell in enumerate(nb.get("cells", [])):
        src = "".join(cell.get("source", []))
        outputs = cell.get("outputs", [])
        preview = ""
        if outputs:
            first = outputs[0]
            text = first.get("text") or first.get("data", {}).get("text/plain", [])
            preview = "".join(text)[:300]

        result_cells.append({
            "index": i,
            "type": cell["cell_type"],
            "source": src,
            "output_preview": preview,
        })

    return {"status": "ok", "path": path, "n_cells": len(result_cells), "cells": result_cells}


def _check_venv(notebook_path: str) -> tuple[bool, str]:
    """Returns (ok, error_message). Checks that a .venv exists next to the notebook."""
    nb_dir = Path(notebook_path).parent
    venv = nb_dir / ".venv"
    if not venv.exists():
        return False, (
            f"Aucun .venv trouvé dans {nb_dir}. "
            "Crée-le d'abord : shell_run(\"python -m venv .venv\") "
            "puis installe les dépendances : shell_run(\".venv/bin/pip install <pkg>\"). "
            "Ne jamais éditer un notebook sans .venv."
        )
    return True, ""


@tool("notebook_edit_cell")
def notebook_edit_cell(path: str, cell_index: int, new_source: str) -> Dict[str, Any]:
    """
    Proposes editing the source of a single notebook cell WITHOUT writing to disk.
    The user will see a before/after diff of just this cell and can approve/reject/refine.
    ALWAYS use this instead of propose_file_change when editing a .ipynb file.
    PREREQUISITE: a .venv must exist in the notebook's directory.

    Args:
        path:       absolute path to the .ipynb file
        cell_index: zero-based index of the cell to edit (use notebook_read to get indices)
        new_source: complete new source for the cell
    Returns:
        {"status": "proposed", "cell_index": N, "awaiting_confirmation": true}
    """
    venv_ok, venv_err = _check_venv(path)
    if not venv_ok:
        return {"status": "error", "error": venv_err}

    try:
        nb = _load(path)
    except Exception as e:
        return {"status": "error", "error": str(e)}

    cells = nb.get("cells", [])
    if not (0 <= cell_index < len(cells)):
        return {"status": "error", "error": f"Index {cell_index} hors limites ({len(cells)} cellules)"}

    cell = cells[cell_index]
    original = "".join(cell.get("source", []))

    pending_cell_changes.add(CellChange(
        path=path,
        cell_index=cell_index,
        insert_after=-1,
        cell_type=cell["cell_type"],
        original_source=original,
        proposed_source=new_source,
        description=f"Édition cellule {cell_index} ({cell['cell_type']})",
    ))

    return {"status": "proposed", "cell_index": cell_index, "cell_type": cell["cell_type"], "awaiting_confirmation": True}


@tool("notebook_insert_cell")
def notebook_insert_cell(path: str, after_index: int, cell_type: str, source: str) -> Dict[str, Any]:
    """
    Proposes inserting a new cell in a notebook WITHOUT writing to disk.
    The user will see the new cell content and can approve/reject/refine.
    ALWAYS use this instead of propose_file_change when adding cells to a .ipynb file.
    PREREQUISITE: a .venv must exist in the notebook's directory.

    Args:
        path:        absolute path to the .ipynb file
        after_index: insert after this cell index (-1 to insert at the very beginning)
        cell_type:   "code" or "markdown"
        source:      source content of the new cell
    Returns:
        {"status": "proposed", "after_index": N, "awaiting_confirmation": true}
    """
    venv_ok, venv_err = _check_venv(path)
    if not venv_ok:
        return {"status": "error", "error": venv_err}

    try:
        nb = _load(path)
    except Exception as e:
        return {"status": "error", "error": str(e)}

    n = len(nb.get("cells", []))
    if not (-1 <= after_index < n):
        return {"status": "error", "error": f"after_index {after_index} hors limites ({n} cellules)"}

    if cell_type not in ("code", "markdown"):
        return {"status": "error", "error": f"cell_type doit être 'code' ou 'markdown'"}

    pending_cell_changes.add(CellChange(
        path=path,
        cell_index=-1,
        insert_after=after_index,
        cell_type=cell_type,
        original_source="",
        proposed_source=source,
        description=f"Insertion cellule {cell_type} après index {after_index}",
    ))

    return {"status": "proposed", "after_index": after_index, "cell_type": cell_type, "awaiting_confirmation": True}


@tool("notebook_run")
def notebook_run(path: str, timeout: int = 120) -> Dict[str, Any]:
    """
    Executes a Jupyter notebook and saves the outputs in-place (via nbconvert).
    Use this after editing cells to verify the code runs correctly.
    PREREQUISITE: a .venv must exist in the notebook's directory.

    Args:
        path:    absolute path to the .ipynb file
        timeout: max execution time in seconds (default 120)
    Returns:
        {"status": "ok"} or {"status": "error", "error": str}
    """
    venv_ok, venv_err = _check_venv(path)
    if not venv_ok:
        return {"status": "error", "error": venv_err}

    p = Path(path)
    if not p.exists():
        return {"status": "error", "error": f"Notebook introuvable : {path}"}

    nb_dir = p.parent
    venv_jupyter = nb_dir / ".venv" / "bin" / "jupyter"
    jupyter_cmd = str(venv_jupyter) if venv_jupyter.exists() else "jupyter"

    try:
        res = subprocess.run(
            [
                jupyter_cmd, "nbconvert",
                "--to", "notebook",
                "--execute",
                "--inplace",
                f"--ExecutePreprocessor.timeout={timeout}",
                str(p),
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            cwd=str(nb_dir),
        )
        if res.returncode != 0:
            return {"status": "error", "error": (res.stderr or res.stdout)[:2000]}
        return {"status": "ok", "message": f"Notebook exécuté avec succès : {path}"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Timeout dépassé lors de l'exécution du notebook."}
    except FileNotFoundError:
        return {"status": "error", "error": "jupyter nbconvert introuvable — pip install jupyter"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
