"""Compatibilité de CONSTRUCTION d'un combo (Lot 9), STRICTEMENT séparée de la
classification de dépendance. Ces contrôles interviennent AVANT `dependency`.

Reason codes dédiés (jamais `DependencyStatus`). `BOOKMAKER_COMBO_UNAVAILABLE`
n'est émis QUE si un refus explicite est trouvé dans un contrat amont : aucun
contrat n'expose cette info en V1 (cf. current-state §10.6) -> chemin inatteignable,
JAMAIS déclenché par absence de donnée (absence ≠ refus)."""

from __future__ import annotations

from ..domain.candidates import CandidateEvaluation
from ..domain.enums import CandidateStatus
from ..domain.requests import RecommendationRequest

DIFFERENT_BOOKMAKERS = "DIFFERENT_BOOKMAKERS"
NON_ELIGIBLE_LEG = "NON_ELIGIBLE_LEG"
FORBIDDEN_MARKET = "FORBIDDEN_MARKET"
DUPLICATE_LEG = "DUPLICATE_LEG"
BOOKMAKER_COMBO_UNAVAILABLE = "BOOKMAKER_COMBO_UNAVAILABLE"   # inatteignable en V1 (pas de donnée amont)

COMPATIBILITY_REASON_CODES = frozenset({
    DIFFERENT_BOOKMAKERS, NON_ELIGIBLE_LEG, FORBIDDEN_MARKET, DUPLICATE_LEG,
    BOOKMAKER_COMBO_UNAVAILABLE,
})


def _market_forbidden(candidate, request: RecommendationRequest) -> bool:
    if request.allowed_market_types is not None and candidate.market_type not in request.allowed_market_types:
        return True
    return candidate.market_type in request.excluded_market_types


def check_compatibility(
    a: CandidateEvaluation, b: CandidateEvaluation, request: RecommendationRequest,
) -> str | None:
    """Premier code de compatibilité applicable, ou `None` si la paire peut
    passer à la classification de dépendance."""
    if a.candidate.candidate_id == b.candidate.candidate_id:
        return DUPLICATE_LEG                                  # (A, A) — jamais INCOMPATIBLE
    if a.status is not CandidateStatus.ELIGIBLE or b.status is not CandidateStatus.ELIGIBLE:
        return NON_ELIGIBLE_LEG                               # REVIEW_ONLY/REJECTED jamais dans un combo
    if a.candidate.bookmaker != b.candidate.bookmaker:
        return DIFFERENT_BOOKMAKERS                           # combo mono-bookmaker (jamais UNKNOWN)
    if _market_forbidden(a.candidate, request) or _market_forbidden(b.candidate, request):
        return FORBIDDEN_MARKET
    # BOOKMAKER_COMBO_UNAVAILABLE : aucune donnée amont en V1 -> non déclenché
    # (absence ≠ indisponible). Chemin réservé à une évolution de contrat.
    return None
