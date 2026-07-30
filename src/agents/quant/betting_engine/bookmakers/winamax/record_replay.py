"""Record / replay d'un `PRELOADED_STATE` Winamax — infrastructure pour capturer un
payload RÉEL plus tard et le rejouer hors-ligne, SANS jamais fabriquer un payload
qui prétendrait être réel.

Le parsing (`connector.parse_catalog`) est déjà pur ; il ne manque que la capture
persistée + sa PROVENANCE honnête. Une capture porte sa `source` :
  - `SOURCE_LIVE`   : produite par un vrai fetch réseau (`capture_live_state`) ;
  - `SOURCE_SYNTHETIC` : construite à la main (fixtures de test), jamais présentée
    comme réelle.
La source est persistée verbatim : un replay ne peut donc pas mentir sur l'origine
de ses événements. Aucun pari réel n'est jamais placé ici.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone

from ..protocol import RawBookmakerEvent
from .connector import SPORT_IDS, _fetch_state, parse_catalog

SOURCE_LIVE = "winamax.fr/live"
SOURCE_SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class StateCapture:
    sport: str
    sport_id: int
    source: str                  # SOURCE_LIVE | SOURCE_SYNTHETIC — jamais confondus
    captured_at: str             # ISO 8601
    preloaded_state: dict

    @property
    def is_authentic(self) -> bool:
        return self.source == SOURCE_LIVE


def capture_live_state(sport: str, *, fetch=_fetch_state, now: datetime | None = None) -> StateCapture:
    """Capture un état RÉEL via le réseau (source LIVE). `fetch` injectable pour les
    tests (aucun réseau réel exigé en CI). N'est marqué LIVE que si réellement fetché."""
    sport_id = SPORT_IDS.get(sport.lower())
    if sport_id is None:
        raise ValueError(f"sport inconnu : {sport}")
    state = fetch(sport_id)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    return StateCapture(sport.lower(), sport_id, SOURCE_LIVE, stamp, state)


def synthetic_capture(preloaded_state: dict, sport: str, *, now: datetime | None = None) -> StateCapture:
    """Capture explicitement SYNTHÉTIQUE (fixtures). Jamais marquée LIVE."""
    sport_id = SPORT_IDS.get(sport.lower())
    if sport_id is None:
        raise ValueError(f"sport inconnu : {sport}")
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    return StateCapture(sport.lower(), sport_id, SOURCE_SYNTHETIC, stamp, preloaded_state)


def save_capture(capture: StateCapture, path: pathlib.Path) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "sport": capture.sport,
        "sport_id": capture.sport_id,
        "source": capture.source,            # provenance persistée verbatim
        "captured_at": capture.captured_at,
        "preloaded_state": capture.preloaded_state,
    }, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def load_capture(path: pathlib.Path) -> StateCapture:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return StateCapture(
        sport=data["sport"], sport_id=data["sport_id"], source=data["source"],
        captured_at=data["captured_at"], preloaded_state=data["preloaded_state"],
    )


def replay(capture: StateCapture, *, now: datetime | None = None) -> list[RawBookmakerEvent]:
    """Rejoue une capture -> événements bruts, sans réseau. Transformation identique
    au chemin live (même `parse_catalog`)."""
    return parse_catalog(capture.preloaded_state, capture.sport, capture.sport_id, now=now)
