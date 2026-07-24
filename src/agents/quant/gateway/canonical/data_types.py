"""Vocabulaire fermé des `data_type` (PRD v2 §5.2).

Partagé par le provider_coverage_registry, le fallback_chain et les
consommateurs — un `data_type` n'est jamais une chaîne libre.

FIXTURES = matchs À VENIR (programmés, sans score) ;
RESULTS  = matchs TERMINÉS (joués, avec score).
La distinction est explicite dès le socle : un même appel provider (ex.
`/matches`) peut renvoyer les deux, ils sont classés par statut de match
lors de la normalisation (arbitrage Vague 0 : scinder FIXTURES / RESULTS).

Un sport ne supporte pas forcément tous les types (SportModule.supported_data_types).
Ex. RANKINGS est pertinent en tennis, pas au football de clubs.
"""

from __future__ import annotations
from enum import Enum


class DataType(str, Enum):
    FIXTURES = "FIXTURES"                  # matchs programmés, non joués
    RESULTS = "RESULTS"                    # matchs terminés, avec score final
    STANDINGS = "STANDINGS"                # classement d'une compétition
    TEAM_STATS = "TEAM_STATS"
    PLAYER_STATS = "PLAYER_STATS"
    LINEUPS = "LINEUPS"                    # compositions (foot, pitcher partant baseball)
    INJURIES = "INJURIES"
    RANKINGS = "RANKINGS"                  # classement de joueurs (tennis ATP/WTA)
    HEAD_TO_HEAD_RAW = "HEAD_TO_HEAD_RAW"
    SQUAD = "SQUAD"


def is_valid_data_type(value: str) -> bool:
    """True si `value` appartient au vocabulaire fermé."""
    try:
        DataType(value)
        return True
    except ValueError:
        return False
