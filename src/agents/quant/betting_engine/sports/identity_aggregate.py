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
    """Toutes les identités canoniques des sports enregistrés.

    Cette fonction énumérait les référentiels un par un (`TEAMS`, `NBA_TEAMS`,
    `NHL_TEAMS`, …). Elle produisait exactement le même ensemble que
    `registry.all_known_entities()`, mais par une liste maintenue à la main : un
    sport ajouté au registre restait invisible ici jusqu'à ce que quelqu'un y
    pense. Deux énumérations d'une même vérité ne divergent pas le jour où on
    les écrit, elles divergent six mois plus tard.

    Le registre est la source ; ce nom reste comme alias historique.
    """
    from .registry import all_known_entities
    return tuple(all_known_entities())
