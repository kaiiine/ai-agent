"""Audit STRUCTUREL d'une recommandation (PRD §19). Produit un `audit_id`
déterministe et un enregistrement sérialisable (instantané). La PERSISTANCE
(backend append-only, replay, migrations) est différée au Lot 10 / ADR-ADV-012 :
ici, aucune écriture disque."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from ..domain.recommendations import RecommendationResponse
from ..domain.requests import RecommendationRequest


def audit_id_for(
    request: RecommendationRequest, *, ranking_profile_name: str, evaluation_ids: Sequence[str],
) -> str:
    """Déterministe : même requête + mêmes candidats + même profil -> même id."""
    payload = "|".join((
        request.request_id, request.decision_time.isoformat(),
        ranking_profile_name, *sorted(evaluation_ids),
    ))
    return "audit:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def build_audit_record(
    request: RecommendationRequest, response: RecommendationResponse, *,
    ranking_profile_name: str,
) -> dict:
    """Instantané structurel (sans persistance). Réutilisable tel quel par la
    couche d'audit persistée du Lot 10."""
    return {
        "audit_id": response.audit_id,
        "request_id": request.request_id,
        "decision_time": request.decision_time.isoformat(),
        "ranking_profile": ranking_profile_name,
        "risk_profile": request.risk_profile.value,
        "maturity_policy": request.maturity_policy.value,
        "outcome": response.outcome.value,
        "n_portfolios": len(response.portfolios),
        "n_review_candidates": len(response.review_candidates),
        "rejection_summary": dict(response.rejection_summary),
    }
