"""Couche conversationnelle du betting — la SEULE porte entre le LLM et l'Advisor.

Le chemin autorisé, et le seul :

    demande utilisateur
      -> UserBettingConstraints (state typé, fusionné entre les tours)
      -> TimeWindow (Europe/Paris, résolue en absolu)
      -> RecommendationRequest
      -> scan Winamax -> Betting Engine -> Adapter -> Advisor
      -> RecommendationResponse + BettingResponseEvidence
      -> renderer déterministe

Le LLM traduit la demande et explique la réponse. Il n'est propriétaire d'aucun
fait sportif : ni catalogue, ni horaire, ni cote, ni probabilité, ni EV, ni
décision, ni combiné, ni mise.
"""

from .constraints import UserBettingConstraints, merge_constraints
from .evidence import BettingResponseEvidence
from .window import TimeWindow, resolve_window

__all__ = [
    "BettingResponseEvidence",
    "TimeWindow",
    "UserBettingConstraints",
    "merge_constraints",
    "resolve_window",
]
