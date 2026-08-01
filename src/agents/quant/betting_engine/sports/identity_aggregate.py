"""Identités canoniques AGRÉGÉES multisport (finalization §3).

Le résolveur partagé (collecte CLV) était football-only (`gateway.identity_data.TEAMS`).
Cette agrégation réunit les identités de TOUS les sports live-câblés (football + basket +
hockey), pour que la collecte odds_history résolve un événement hockey/basket comme un
événement football. Aucun `if sport ==` : le `BookmakerEventResolver` filtre déjà par
préfixe `team:{sport}:` — les espaces de noms par sport ne se croisent jamais.

Les identités par sport restent DÉCLARÉES dans leur module (NBA_TEAMS, NHL_TEAMS) ; ici on
se contente de les réunir. Un sport dont l'identité live n'est pas encore peuplée n'apparaît
pas — ses événements restent explicitement non résolus (jamais devinés).
"""

from __future__ import annotations

from functools import lru_cache

from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity


@lru_cache(maxsize=1)
def all_sport_teams() -> tuple[CanonicalEntity, ...]:
    """Toutes les identités d'équipes des 6 sports live-câblés (football + basket + hockey
    + baseball + NFL + volley). Espaces de noms disjoints par préfixe `team:{sport}:` →
    aucune collision inter-sports (le résolveur filtre déjà par sport)."""
    from src.agents.quant.gateway.core.identity_data import TEAMS
    from .basketball.live_model import NBA_TEAMS
    from .hockey.live_model import NHL_TEAMS
    from .baseball.live_model import MLB_TEAMS
    from .american_football.live_model import NFL_TEAMS
    from .volleyball.live_model import VOLLEY_TEAMS
    return (tuple(TEAMS) + tuple(NBA_TEAMS) + tuple(NHL_TEAMS)
            + tuple(MLB_TEAMS) + tuple(NFL_TEAMS) + tuple(VOLLEY_TEAMS))
