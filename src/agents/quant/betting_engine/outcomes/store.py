"""Store JSONL append-only des prédictions et de leur règlement.

Même frontière que `clv/store.py` — chemin injectable, `var/` repo-local, jamais
`~/.axon`, Decimal sérialisé en chaîne. Un backend transactionnel pourra la
remplacer sans toucher au domaine.

Append-only y compris pour le règlement : régler écrit une NOUVELLE ligne, et la
lecture garde la plus récente par clé. L'historique d'un règlement reste donc
lisible, et une issue ne peut pas être effacée — seulement corrigée visiblement.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

from .record import Issue, PredictionRecord

_DEFAULT_STORE = (
    pathlib.Path(__file__).resolve().parents[5]
    / "var" / "betting_engine" / "predictions.jsonl"
)


class JsonlPredictionStore:
    def __init__(self, path: pathlib.Path | None = None):
        self.path = pathlib.Path(path) if path is not None else _DEFAULT_STORE
        if str(self.path).startswith("~") or "~/.axon" in str(self.path):
            raise ValueError("predictions : chemin ~/.axon interdit")

    def append(self, record: PredictionRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_to_jsonable(record), sort_keys=True,
                               ensure_ascii=False) + "\n")

    def iter_raw(self) -> Iterator[PredictionRecord]:
        """Toutes les lignes, dans l'ordre d'écriture — y compris les états
        antérieurs d'une même prédiction."""
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield _from_jsonable(json.loads(line))

    def all(self) -> list[PredictionRecord]:
        """État COURANT : une entrée par prédiction, la dernière écrite gagne.

        Sans cette réduction, une prédiction réglée serait comptée deux fois par
        la calibration — une fois non réglée, une fois réglée.
        """
        courant: dict[tuple[str, str, str], PredictionRecord] = {}
        for record in self.iter_raw():
            courant[record.cle] = record
        return list(courant.values())

    def non_reglees(self) -> list[PredictionRecord]:
        return [r for r in self.all() if not r.est_reglee]


def _to_jsonable(r: PredictionRecord) -> dict:
    return {
        "stable_event_id": r.stable_event_id,
        "market_type": r.market_type,
        "selection": r.selection,
        "participant_ids": list(r.participant_ids),
        "model_version": r.model_version,
        "fair_probability": str(r.fair_probability),
        "bookmaker_odds": None if r.bookmaker_odds is None else str(r.bookmaker_odds),
        "bookmaker": r.bookmaker,
        "scheduled_at": r.scheduled_at.isoformat(),
        "decided_at": r.decided_at.isoformat(),
        "run_id": r.run_id,
        "issue": None if r.issue is None else r.issue.value,
        "settled_at": None if r.settled_at is None else r.settled_at.isoformat(),
        "settlement_source": r.settlement_source,
    }


def _from_jsonable(d: dict) -> PredictionRecord:
    cotes = d.get("bookmaker_odds")
    regle = d.get("settled_at")
    return PredictionRecord(
        stable_event_id=d["stable_event_id"],
        market_type=d["market_type"],
        selection=d["selection"],
        participant_ids=tuple(d.get("participant_ids") or ()),
        model_version=d["model_version"],
        fair_probability=Decimal(d["fair_probability"]),
        bookmaker_odds=None if cotes is None else Decimal(cotes),
        bookmaker=d.get("bookmaker"),
        scheduled_at=datetime.fromisoformat(d["scheduled_at"]),
        decided_at=datetime.fromisoformat(d["decided_at"]),
        run_id=d.get("run_id"),
        issue=None if d.get("issue") is None else Issue(d["issue"]),
        settled_at=None if regle is None else datetime.fromisoformat(regle),
        settlement_source=d.get("settlement_source"),
    )
