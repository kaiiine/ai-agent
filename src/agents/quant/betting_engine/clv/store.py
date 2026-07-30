"""Store `odds_history` JSONL append-only (BE-FR-015). Une observation de cote par
ligne JSON, jamais mutée. Chemin INJECTABLE (tests : tmp_path) ; défaut repo-local
sous `var/` (déjà gitignoré), JAMAIS `~/.axon`. Decimal sérialisé en chaîne
canonique (jamais float).

Frontière volontairement identique à celle de l'audit Advisor : un backend
transactionnel pourra la remplacer sans toucher au domaine CLV.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

from .observation import ObservationPhase, OddsObservation

_DEFAULT_STORE = (
    pathlib.Path(__file__).resolve().parents[5]
    / "var" / "betting_engine" / "odds_history.jsonl"
)


class JsonlOddsHistoryStore:
    def __init__(self, path: pathlib.Path | None = None):
        self.path = pathlib.Path(path) if path is not None else _DEFAULT_STORE
        if "~/.axon" in str(self.path) or str(self.path).startswith("~"):
            raise ValueError("odds_history : chemin ~/.axon interdit")

    def append(self, obs: OddsObservation) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_to_jsonable(obs), sort_keys=True, ensure_ascii=False) + "\n")

    def iter_observations(self) -> Iterator[OddsObservation]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield _from_jsonable(json.loads(line))

    def all(self) -> list[OddsObservation]:
        return list(self.iter_observations())


def _to_jsonable(obs: OddsObservation) -> dict:
    return {
        "event_id": obs.event_id,
        "market_type": obs.market_type,
        "selection": obs.selection,
        "bookmaker": obs.bookmaker,
        "decimal_odds": str(obs.decimal_odds),        # Decimal -> str (jamais float)
        "observed_at": obs.observed_at.isoformat(),
        "phase": obs.phase.value,
        "source": obs.source,
        "source_event_id": obs.source_event_id,
        "run_id": obs.run_id,
    }


def _from_jsonable(data: dict) -> OddsObservation:
    return OddsObservation(
        event_id=data["event_id"],
        market_type=data["market_type"],
        selection=data["selection"],
        bookmaker=data["bookmaker"],
        decimal_odds=Decimal(data["decimal_odds"]),
        observed_at=datetime.fromisoformat(data["observed_at"]),
        phase=ObservationPhase(data["phase"]),
        source=data["source"],
        source_event_id=data.get("source_event_id"),
        run_id=data.get("run_id"),
    )
