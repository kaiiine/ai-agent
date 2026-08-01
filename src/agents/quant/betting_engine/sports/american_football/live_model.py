"""NFL — modèle LIVE moneyline « Vainqueur » (2-way) câblé via le harness pairwise.

Ferme le chemin live NFL (§10) : identité NFL dérivée de la fixture -> Elo point-in-time
-> probas home/away -> EXPERIMENTAL -> ABSTAIN. Settlement « Vainqueur » (issue du match,
prolongation incluse) ; les rares nuls NFL sont EXCLUS du dataset d'entraînement (le
marché Winamax vérifié est 2-way). Terrains neutres (Londres/Super Bowl) : traités comme
tout match — l'avantage domicile est un prior Elo, non une certitude. Aucun nouveau modèle.
"""

from __future__ import annotations

import functools

from ..pairwise_live import build_identity, make_module, team_directory
from .moneyline import MODEL_NAME, MODEL_VERSION, NFL_PARAMS, _FIXTURE, load_nfl_games

_DIRECTORY = team_directory(_FIXTURE, id_home="home", id_away="away",
                            name_home="home_name", name_away="away_name")
NFL_TEAMS, _API_OF = build_identity(_DIRECTORY, sport="american_football", league="nfl",
                                    meta_key="api_american_football")


@functools.lru_cache(maxsize=1)
def _games():
    games, _fp = load_nfl_games()
    return games


NFL_MODULE = make_module(
    sport="american_football", games_fn=_games, api_of=_API_OF, params=NFL_PARAMS,
    model_name=MODEL_NAME, model_version=MODEL_VERSION, feature_version="nfl-elo-1.0")
