"""NFL — moneyline « Vainqueur » (2-way) via le harness Elo pairwise générique.

Sémantique de marché VÉRIFIÉE sur le payload Winamax (sportId 16) : bet « Vainqueur »,
template 2way, 2 issues, AUCUN nul → compatible harness pairwise 2-way.

PARAMÈTRES PROPRES au NFL (documentés, NON hérités) :
- `home_edge=48` : avantage domicile NFL ~57 % (≈ 48 points Elo) ;
- `k_factor=20` : K standard des Elo NFL (saisons courtes, forte info par match) ;
- `min_prior_games=6` : cold-start réduit (17 matchs/saison → historique inter-saisons requis).
Skill VALIDÉ hors échantillon (Brier modèle < baseline). Verdict mécanique EXPERIMENTAL.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.agents.quant.betting_engine.calibration.experiment_registry import dataset_fingerprint
from src.agents.quant.betting_engine.live_coverage import live_freshness_capability
from src.agents.quant.betting_engine.sports.pairwise_elo import (
    EloParams,
    PairwiseAssessment,
    PairwiseGame,
    assess_pairwise_elo,
)

MODEL_NAME = "american_football_moneyline"
MODEL_VERSION = "nfl.moneyline.elo.v0"
NFL_LEAGUE_ID = "competition:american_football:usa:nfl"

NFL_PARAMS = EloParams(
    init_rating=1500.0, k_factor=20.0, home_edge=48.0, min_prior_games=6,
    notes="NFL: home ~57% -> home_edge 48 ; K=20 (Elo NFL standard) ; cold-start 6 (17 matchs/saison)")

_FIXTURE = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "nfl_api_sports_games.json"


def load_nfl_games(path: Path = _FIXTURE) -> tuple[list[PairwiseGame], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    def _ts(raw: str) -> datetime:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)   # dates NFL = jour seul -> UTC

    games = [
        PairwiseGame(
            game_id=str(g["id"]),
            tipoff=_ts(str(g["date"])),
            home_id=str(g["home"]), away_id=str(g["away"]),
            home_score=int(g["hs"]), away_score=int(g["as"]),
        )
        for g in data["games"] if int(g["hs"]) != int(g["as"])   # pas de nul retenu
    ]
    return games, dataset_fingerprint(raw)


def assess_nfl(path: Path = _FIXTURE, *, odds_observations=()) -> PairwiseAssessment:
    games, _fp = load_nfl_games(path)
    # Freshness live CÂBLÉE (test_pairwise_live) -> MEASURABLE. CLV reste NOT_YET_MEASURABLE.
    # `odds_observations` alimente la CLV RÉELLE. Le paramètre manquait : la
    # collecte pouvait remplir l'historique sans que le critère bouge jamais.
    return assess_pairwise_elo(games, NFL_PARAMS, MODEL_NAME, MODEL_VERSION,
                              odds_observations=odds_observations,
                              live_freshness_status=live_freshness_capability(NFL_LEAGUE_ID))
