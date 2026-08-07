"""Volley — moneyline « Vainqueur » (2-way) via le harness Elo pairwise générique.

Sémantique VÉRIFIÉE (Winamax sportId 23 : « Vainqueur » 2-way, aucun nul — le match se
joue en sets jusqu'à décision). L'issue = qui a gagné le plus de sets.

PARAMÈTRES PROPRES au volley (documentés, DÉRIVÉS des données, non copiés) :
- `home_edge=33` : taux de victoire domicile MESURÉ = 0.547 sur le dataset → 33 pts Elo
  (dérivé, pas un prior arbitraire) ;
- `k_factor=20` ; `min_prior_games=5`.
Skill FORT hors échantillon (Brier 0.363 ≪ baseline 0.499 : le volley est très prévisible
par rating, faible taux d'upset). Verdict mécanique EXPERIMENTAL (échantillon < 500).
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

MODEL_NAME = "volleyball_moneyline"
MODEL_VERSION = "volleyball.moneyline.elo.v0"
VOLLEY_LEAGUE_ID = "competition:volleyball:ita:serie_a1"

VOLLEY_PARAMS = EloParams(
    init_rating=1500.0, k_factor=20.0, home_edge=33.0, min_prior_games=5,
    notes="Volley Serie A1 ITA : home_win_rate mesuré 0.547 -> home_edge 33 (DÉRIVÉ) ; K=20 ; cold-start 5")

_FIXTURE = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "volley_api_sports_games.json"


def load_volleyball_games(path: Path = _FIXTURE) -> tuple[list[PairwiseGame], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    games = [
        PairwiseGame(
            game_id=str(g["id"]),
            tipoff=datetime.fromisoformat(str(g["date"]).replace("Z", "+00:00")),
            home_id=str(g["home"]), away_id=str(g["away"]),
            home_score=int(g["hs"]), away_score=int(g["as"]),   # sets gagnés
        )
        for g in data["games"] if int(g["hs"]) != int(g["as"])
    ]
    return games, dataset_fingerprint(raw)


def assess_volleyball(path: Path = _FIXTURE) -> PairwiseAssessment:
    games, _fp = load_volleyball_games(path)
    # Freshness live CÂBLÉE (test_pairwise_live) -> MEASURABLE. CLV reste NOT_YET_MEASURABLE.
    return assess_pairwise_elo(games, VOLLEY_PARAMS, MODEL_NAME, MODEL_VERSION,
                              live_freshness_status=live_freshness_capability(VOLLEY_LEAGUE_ID))
