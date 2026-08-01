"""Volley — modèle LIVE moneyline « Vainqueur » (2-way) câblé via le harness pairwise.

Ferme le chemin live volley (§11) : identité dérivée de la fixture -> Elo point-in-time
-> probas home/away -> EXPERIMENTAL -> ABSTAIN. Settlement « Vainqueur » = qui gagne le
plus de sets (aucun nul).

NON whitelisté Serie A1 (§11) : l'identité vient des DONNÉES du sport, pas d'une liste
codée en dur. Le dataset embarqué est aujourd'hui la Serie A1 italienne, donc seules ces
équipes résolvent ; une autre compétition compatible entre en AJOUTANT ses données —
sans toucher à ce code (aucun `if league == "serie_a1"`).
"""

from __future__ import annotations

import functools

from ..pairwise_live import build_identity, make_module, team_directory
from .moneyline import MODEL_NAME, MODEL_VERSION, VOLLEY_PARAMS, _FIXTURE, load_volleyball_games

# `league` générique = espace d'identité du sport (pas une compétition figée) : d'autres
# compétitions peupleront le même espace `team:volleyball:club:*` en ajoutant des données.
_DIRECTORY = team_directory(_FIXTURE, id_home="home", id_away="away",
                            name_home="home_name", name_away="away_name")
VOLLEY_TEAMS, _API_OF = build_identity(_DIRECTORY, sport="volleyball", league="club",
                                       meta_key="api_volleyball")


@functools.lru_cache(maxsize=1)
def _games():
    games, _fp = load_volleyball_games()
    return games


VOLLEYBALL_MODULE = make_module(
    sport="volleyball", games_fn=_games, api_of=_API_OF, params=VOLLEY_PARAMS,
    model_name=MODEL_NAME, model_version=MODEL_VERSION, feature_version="volleyball-elo-1.0")
