"""Basket NBA — marchés de SCORE : écart de points et nombre de points.

L'Elo moneyline du même sport n'est ni utilisé ni modifié. Il répond à « qui
gagne » ; en dériver un écart de points reviendrait à inventer la dispersion,
c'est-à-dire précisément la quantité que le marché du handicap cote.

PARAMÈTRES PROPRES AU BASKET, choisis AVANT le benchmark et non réajustés :

    baseline_points 112  points par équipe et par match, ordre de grandeur NBA
    k               0,05 une erreur de 20 points déplace la note d'un demi-point
    home_edge       2,7  avantage du terrain EN POINTS, valeur usuelle NBA
    min_prior_games 10   sous ce seuil, les notes valent encore leur initialisation
    min_prior_residuals 200  en deçà, l'écart-type mesuré ne veut rien dire

MESURÉ (walk-forward strict, 4 149 rencontres 2022-2025, 3 944 évaluées) :

    loi NORMAL   24 cibles sur 24 battent leur baseline point-in-time
                 ECE moyen 0,0144 · ECE max 0,0346
                 MAE marge 10,90 pt · MAE total 14,78 pt
    loi POISSON  24/24 mais ECE moyen 0,0249 — la surdispersion mesurée du total
                 (variance/moyenne = 1,88) est incompatible avec Poisson
    loi NEGBIN   22/24 · ECE moyen 0,0281

LE DOMAINE EST LA NBA, ET SEULEMENT ELLE. Le corpus embarqué ne contient aucune
rencontre WNBA, EuroLeague ou universitaire : appliquer ces notes à un autre
championnat produirait des probabilités sur des équipes que le modèle n'a jamais
vues. C'est le garde de domaine qui doit le refuser, pas ce commentaire.
"""

from __future__ import annotations

from src.agents.quant.betting_engine.sports.score_distribution import ScoreGame, ScoreParams
from src.agents.quant.betting_engine.sports.score_markets import ScoreMarketConfig

MODEL_NAME = "basketball_score"
MODEL_VERSION = "basketball.score.normal.v0"
NBA_LEAGUE_ID = "competition:basketball:usa:nba"

NBA_SCORE_PARAMS = ScoreParams(
    baseline_points=112.0, k=0.05, home_edge=2.7,
    min_prior_games=10, min_prior_residuals=200,
    notes="NBA : ~112 pts/équipe, avantage domicile ~2,7 pts, K=0,05")


def _identites_nba() -> dict:
    """`canonical_id -> id api-sports`, repris du modèle moneyline du sport."""
    from .live_model import _API_TO_CANONICAL
    return {canonique: api for api, canonique in _API_TO_CANONICAL.items()}


def load_nba_score_games() -> list[ScoreGame]:
    """Le MÊME corpus que le moneyline, lu pour son SCORE et non son vainqueur."""
    from .moneyline import load_nba_games
    jeux, _ = load_nba_games()
    return [ScoreGame(g.game_id, g.tipoff, g.home_team_id, g.away_team_id,
                      g.home_points, g.away_points) for g in jeux]


NBA_SCORE_CONFIG = ScoreMarketConfig(
    sport="basketball", competition_id=NBA_LEAGUE_ID,
    model_name=MODEL_NAME, model_version=MODEL_VERSION,
    params=NBA_SCORE_PARAMS, load=load_nba_score_games,
    law="NORMAL", team_id_of=_identites_nba)
