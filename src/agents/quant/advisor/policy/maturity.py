"""Table de maturité (PRD §11.2) — statut de base d'un candidat selon la maturité
du modèle et la politique de la requête.

Ne rehausse JAMAIS la maturité (aucun EXPERIMENTAL -> SUPPORTED). Une maturité
inconnue échoue bruyamment plutôt que d'être devinée."""

from __future__ import annotations

from ..domain.enums import CandidateStatus, MaturityPolicy
from . import reason_codes

# Maturités toujours rejetées, quelle que soit la politique (§11.2).
_ALWAYS_REJECTED = frozenset({"INSUFFICIENT_DATA", "UNSUPPORTED", "DEPRECATED"})


def maturity_decision(
    model_maturity: str, policy: MaturityPolicy,
) -> tuple[CandidateStatus, str | None]:
    """(statut de base, raison éventuelle). SUPPORTED -> ELIGIBLE (sans raison) ;
    EXPERIMENTAL -> REVIEW_ONLY (INCLUDE) ou REJECTED (SUPPORTED_ONLY) ; les autres
    -> REJECTED. La raison accompagne REVIEW_ONLY et REJECTED, jamais ELIGIBLE."""
    if model_maturity == "SUPPORTED":
        return CandidateStatus.ELIGIBLE, None

    if model_maturity == "EXPERIMENTAL":
        if policy is MaturityPolicy.INCLUDE_EXPERIMENTAL_FOR_REVIEW:
            return CandidateStatus.REVIEW_ONLY, reason_codes.EXPERIMENTAL_REVIEW_ONLY
        return CandidateStatus.REJECTED, reason_codes.MODEL_NOT_SUPPORTED

    if model_maturity in _ALWAYS_REJECTED:
        return CandidateStatus.REJECTED, reason_codes.MODEL_NOT_SUPPORTED

    # Maturité hors contrat connu : refus explicite (jamais deviné).
    raise ValueError(f"maturité de modèle inconnue : {model_maturity!r}")
