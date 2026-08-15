"""NFL — marchés de SCORE : écart de points et nombre de points.

Le corpus NFL est le plus long dont dispose AXON : 7 405 rencontres de 1999 à
2026, api-sports complété par nflverse (CC-BY-4.0). C'est ce qui permet une
mesure fiable là où une saison de dix-sept matchs n'en autoriserait aucune.

PARAMÈTRES PROPRES AU NFL, choisis AVANT le benchmark :

    baseline_points 22   points par équipe et par match
    k               0,06 saisons courtes : chaque match porte plus d'information
    home_edge       1,8  avantage du terrain EN POINTS
    min_prior_games 6    17 matchs par saison — le cold-start doit rester bref
    min_prior_residuals 150

MESURÉ (walk-forward strict, 7 231 rencontres évaluées) :

    loi NORMAL   24 cibles sur 24 battent leur baseline · ECE moyen 0,0176
                 MAE marge 10,79 pt · MAE total 10,90 pt
    loi POISSON  2 cibles sur 24 · ECE moyen 0,1188 — REJETÉE. La surdispersion
                 mesurée du total vaut 4,52, soit quatre fois et demie ce que
                 Poisson autorise ; la loi est structurellement fausse ici, et
                 ses probabilités le montrent.
    loi NEGBIN   24/24 · ECE 0,0181, mais seulement 6 102 rencontres évaluées :
                 son support tronqué en écarte 1 129 sans rien gagner en
                 calibration. À population plus faible et calibration égale, on
                 garde la loi qui price plus de rencontres.
"""

from __future__ import annotations

from src.agents.quant.betting_engine.sports.score_distribution import ScoreGame, ScoreParams
from src.agents.quant.betting_engine.sports.score_markets import ScoreMarketConfig

MODEL_NAME = "american_football_score"
MODEL_VERSION = "american_football.score.normal.v0"
NFL_LEAGUE_ID = "competition:american_football:usa:nfl"

NFL_SCORE_PARAMS = ScoreParams(
    baseline_points=22.0, k=0.06, home_edge=1.8,
    min_prior_games=6, min_prior_residuals=150,
    notes="NFL : ~22 pts/équipe, avantage domicile ~1,8 pt, K=0,06")


def _identites_nfl() -> dict:
    """`canonical_id -> id api-sports`, repris du modèle moneyline du sport."""
    from .live_model import _API_OF
    return dict(_API_OF)


def load_nfl_score_games() -> list[ScoreGame]:
    from .moneyline import load_nfl_games
    jeux, _ = load_nfl_games()
    return [ScoreGame(g.game_id, g.tipoff, g.home_id, g.away_id,
                      g.home_score, g.away_score) for g in jeux]


NFL_SCORE_CONFIG = ScoreMarketConfig(
    sport="american_football", competition_id=NFL_LEAGUE_ID,
    model_name=MODEL_NAME, model_version=MODEL_VERSION,
    params=NFL_SCORE_PARAMS, load=load_nfl_score_games,
    law="NORMAL", team_id_of=_identites_nfl)
