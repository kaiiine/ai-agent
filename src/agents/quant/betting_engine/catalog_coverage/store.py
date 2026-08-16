"""Historique de couverture, JSONL append-only.

Même frontière que `clv/store.py` et `outcomes/store.py` : chemin injectable,
`var/` repo-local, jamais `~/.axon`. Une mesure par run — c'est la série qui dit
si un onboarding a réellement élargi la couverture, ou seulement déplacé un
blocage.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator

_DEFAULT_STORE = (
    pathlib.Path(__file__).resolve().parents[5]
    / "var" / "betting_engine" / "coverage.jsonl"
)


class JsonlCoverageStore:
    def __init__(self, path: pathlib.Path | None = None):
        self.path = pathlib.Path(path) if path is not None else _DEFAULT_STORE
        if str(self.path).startswith("~") or "~/.axon" in str(self.path):
            raise ValueError("coverage : chemin ~/.axon interdit")

    def append(self, couverture) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(couverture.as_dict(), sort_keys=True,
                               ensure_ascii=False) + "\n")

    def iter_mesures(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for ligne in f:
                if ligne.strip():
                    yield json.loads(ligne)

    def all(self) -> list[dict]:
        return list(self.iter_mesures())

    def derniere(self) -> dict | None:
        mesures = self.all()
        return mesures[-1] if mesures else None
