"""Hockey NHL — résultat RÉGLEMENTAIRE 3-way via le harness Elo+Davidson générique.

Sémantique VÉRIFIÉE (Winamax sportId 4 : « Résultat » 3-way, nul réglementaire). L'issue
réglementaire est reconstruite des périodes 1-3 (api-sports `periods.first/second/third`) :
un match `AOT` (prolongation) ou `AP` (tirs au but) = **NUL réglementaire** (tied à 60 min).

PARAMÈTRES PROPRES au hockey (documentés, DÉRIVÉS des données) :
- `home_edge=28` : taux domicile réglementaire DÉCISIF mesuré ~0.54 → 28 pts Elo ;
- `k_factor=10` ; `min_prior_games=10` ; `default_draw_rate=0.22` (amorçage de ν).
Skill VALIDÉ hors échantillon : Brier3 0.628 < base-rate 0.649 ET logloss 1.043 < 1.070.
Verdict mécanique EXPERIMENTAL.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.agents.quant.betting_engine.calibration.experiment_registry import dataset_fingerprint
from src.agents.quant.betting_engine.sports.threeway_davidson import (
    Davidson3Params,
    ThreeWayAssessment,
    ThreeWayGame,
    assess_threeway,
)

MODEL_NAME = "hockey_regulation"
MODEL_VERSION = "nhl.regulation.davidson.v0"
NHL_LEAGUE_ID = "competition:hockey:usa:nhl"

NHL_PARAMS = Davidson3Params(
    init_rating=1500.0, k_factor=10.0, home_edge=28.0, min_prior_games=10, default_draw_rate=0.22,
    notes="NHL réglementaire : home décisif ~0.54 -> home_edge 28 ; K=10 ; ν point-in-time (draw~0.22)")

_FIXTURE = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "nhl_2022_2023_regulation.json"


def load_nhl_regulation(path: Path = _FIXTURE) -> tuple[list[ThreeWayGame], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    games = [
        ThreeWayGame(
            game_id=str(g["id"]),
            tipoff=datetime.fromisoformat(str(g["date"]).replace("Z", "+00:00")),
            home_id=str(g["home"]), away_id=str(g["away"]), outcome=g["o"],   # home | draw | away
        )
        for g in data["games"]
    ]
    return games, dataset_fingerprint(raw)


def assess_nhl(path: Path = _FIXTURE) -> ThreeWayAssessment:
    games, _fp = load_nhl_regulation(path)
    return assess_threeway(games, NHL_PARAMS, MODEL_NAME, MODEL_VERSION)
