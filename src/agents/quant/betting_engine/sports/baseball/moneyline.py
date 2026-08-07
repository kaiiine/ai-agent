"""Baseball MLB — moneyline Elo via le harness pairwise générique.

PARAMÈTRES PROPRES au baseball (documentés, NON hérités du basket — §7) :
- `home_edge=24` : avantage domicile MLB ~54 % (≈ 24 points Elo), pas ~0.60 comme la NBA ;
- `k_factor=4` : baseball = haute variance, faible auto-corrélation match à match -> K bas
  (aligné sur la pratique Elo MLB), très inférieur au K=20 basket ;
- `min_prior_games=20` : saison de 162 matchs -> démarrage à froid plus large.
Skill VALIDÉ hors échantillon (Brier modèle < baseline). Verdict mécanique EXPERIMENTAL.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.agents.quant.betting_engine.calibration.experiment_registry import dataset_fingerprint
from src.agents.quant.betting_engine.live_coverage import live_freshness_capability
from src.agents.quant.betting_engine.sports.pairwise_elo import (
    EloParams,
    PairwiseAssessment,
    PairwiseGame,
    assess_pairwise_elo,
)

MODEL_NAME = "baseball_moneyline"
MODEL_VERSION = "baseball.moneyline.elo.v0"
MLB_LEAGUE_ID = "competition:baseball:usa:mlb"
MLB_SEASON = "2022"

MLB_PARAMS = EloParams(
    init_rating=1500.0, k_factor=4.0, home_edge=24.0, min_prior_games=20,
    notes="MLB: home ~54% -> home_edge 24 ; K=4 (haute variance) ; cold-start 20/162")

_FIXTURE = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "mlb_api_sports_games.json"


def load_mlb_games(path: Path = _FIXTURE) -> tuple[list[PairwiseGame], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    games = [
        PairwiseGame(
            game_id=str(g["id"]),
            tipoff=datetime.fromisoformat(g["date"].replace("Z", "+00:00")),
            home_id=str(g["home_id"]), away_id=str(g["away_id"]),
            home_score=int(g["home_pts"]), away_score=int(g["away_pts"]),
        )
        for g in data["games"] if int(g["home_pts"]) != int(g["away_pts"])   # pas de nul en MLB
    ]
    return games, dataset_fingerprint(raw)


def assess_mlb(path: Path = _FIXTURE, *, odds_observations=()) -> PairwiseAssessment:
    games, _fp = load_mlb_games(path)
    # Freshness live CÂBLÉE (live_model -> evaluate_live_event -> Gateway.data_freshness,
    # prouvé par test_pairwise_live) -> capacité MEASURABLE. La CLV reste NOT_YET_MEASURABLE.
    # `odds_observations` alimente la CLV RÉELLE. Le paramètre manquait : la
    # collecte pouvait remplir l'historique sans que le critère bouge jamais.
    return assess_pairwise_elo(games, MLB_PARAMS, MODEL_NAME, MODEL_VERSION,
                              odds_observations=odds_observations,
                              live_freshness_status=live_freshness_capability(MLB_LEAGUE_ID))
