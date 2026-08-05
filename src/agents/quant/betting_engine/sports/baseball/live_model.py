"""Baseball MLB — modèle LIVE moneyline (2-way) câblé via le harness pairwise générique.

Ferme le chemin live baseball (§9) : identité MLB dérivée de la fixture -> Elo
point-in-time -> probas home/away -> EXPERIMENTAL -> ABSTAIN. Settlement moneyline :
le vainqueur du match (extra-innings inclus) ; AUCUN nul en MLB (le harness 2-way est
donc le bon modèle de settlement). Pas de modèle de lanceur dans cette vague.
"""

from __future__ import annotations

import functools

from ..pairwise_live import build_identity, make_module, team_directory
from .moneyline import MLB_PARAMS, MODEL_NAME, MODEL_VERSION, _FIXTURE, load_mlb_games

# Matchs des étoiles (AL vs NL) exclus de l'identité live : ce ne sont pas des équipes.
_DIRECTORY = team_directory(_FIXTURE, id_home="home_id", id_away="away_id",
                            name_home="home_name", name_away="away_name",
                            exclude=frozenset({"American League", "National League"}))
MLB_TEAMS, _API_OF = build_identity(_DIRECTORY, sport="baseball", league="mlb", meta_key="api_baseball")


@functools.lru_cache(maxsize=1)
def _games():
    games, _fp = load_mlb_games()
    return games


BASEBALL_MODULE = make_module(
    sport="baseball", games_fn=_games, api_of=_API_OF, params=MLB_PARAMS,
    model_name=MODEL_NAME, model_version=MODEL_VERSION, feature_version="baseball-elo-1.0",
    entities=lambda: list(MLB_TEAMS))
