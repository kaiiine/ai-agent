"""clv/ — odds_history (BE-FR-015) + closing-line value point-in-time.

Structure de collecte des cotes ouverture->clôture et calcul de CLV réel dès qu'une
paire décision/clôture existe. Tant qu'aucune paire n'existe : `NOT_YET_MEASURABLE`,
jamais CLV=0. Aucune valeur de CLV n'est fabriquée.
"""

from .clv import (
    MEASURABLE,
    NOT_YET_MEASURABLE,
    ClvReadiness,
    ClvResult,
    clv_readiness,
    compute_clv,
)
from .observation import ObservationPhase, OddsObservation
from .store import JsonlOddsHistoryStore

__all__ = [
    "MEASURABLE",
    "NOT_YET_MEASURABLE",
    "ClvReadiness",
    "ClvResult",
    "clv_readiness",
    "compute_clv",
    "ObservationPhase",
    "OddsObservation",
    "JsonlOddsHistoryStore",
]
