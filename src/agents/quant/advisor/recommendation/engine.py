"""Moteur de recommandation V1 (PRD §14). Assemble la `RecommendationResponse`
depuis les évaluations Policy (Lot 4) et le classement Ranking (Lot 5).

Mapping des `outcome` (validé) :
  >=1 ELIGIBLE classé et misable -> RECOMMENDED (1 portefeuille, 1 ligne SINGLE)
  0 ELIGIBLE misable + >=1 REVIEW_ONLY -> REVIEW_CANDIDATES
  des candidats présents mais aucun ci-dessus -> NO_OPPORTUNITY
  0 candidat évaluable -> NO_EVALUABLE_EVENTS

Déterministe : `generated_at = request.decision_time` (aucun `now()`)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ..domain.candidates import CandidateEvaluation
from ..domain.enums import CandidateStatus, RecommendationOutcome
from ..domain.recommendations import RecommendationResponse
from ..domain.requests import RecommendationRequest
from ..ranking.sort import RankingResult
from . import audit
from .simple import SizingProfile

if TYPE_CHECKING:                                  # évite le cycle recommendation <-> portfolio
    from ..portfolio.constraints import PortfolioCaps


def _rejection_summary(rejected: Sequence[CandidateEvaluation]) -> dict[str, int]:
    return dict(Counter(reason for ev in rejected for reason in ev.policy_reasons))


def recommend(
    policy_evaluations: Sequence[CandidateEvaluation], ranking_result: RankingResult,
    request: RecommendationRequest, *, sizing_profiles: Mapping[str, SizingProfile],
    caps_config: "Mapping[str, PortfolioCaps]",
    combos: Sequence = (),
) -> RecommendationResponse:
    from ..portfolio import build_portfolios      # lazy : casse le cycle d'import
    review = tuple(e for e in policy_evaluations if e.status is CandidateStatus.REVIEW_ONLY)
    rejected = [e for e in policy_evaluations if e.status is CandidateStatus.REJECTED]
    rejected.extend(ranking_result.non_rankable)
    rejection_summary = _rejection_summary(rejected)

    audit_id = audit.audit_id_for(
        request, ranking_profile_name=request.ranking_profile,
        evaluation_ids=[e.candidate.candidate_id for e in policy_evaluations])
    generated_at = request.decision_time

    def response(outcome, portfolios=(), review_candidates=()):
        return RecommendationResponse(
            request_id=request.request_id, generated_at=generated_at, outcome=outcome,
            portfolios=portfolios, review_candidates=review_candidates,
            rejection_summary=rejection_summary, warnings=(), audit_id=audit_id)

    # RECOMMENDED : portefeuille(s) sur les ELIGIBLE classés (Lot 8) + combos
    # admissibles matérialisés dans le primaire (Lot 9/ADR-ADV-014).
    if ranking_result.ranked:
        portfolios = build_portfolios(
            ranking_result.ranked, request,
            sizing_profiles=sizing_profiles, caps_config=caps_config, combos=combos)
        if portfolios:
            return response(RecommendationOutcome.RECOMMENDED, portfolios=portfolios,
                            review_candidates=review)

    # REVIEW_CANDIDATES : rien de misable mais des candidats à examiner.
    if review:
        return response(RecommendationOutcome.REVIEW_CANDIDATES, review_candidates=review)

    # NO_OPPORTUNITY : des candidats existaient, aucun retenu ni à examiner.
    if policy_evaluations or ranking_result.non_rankable:
        return response(RecommendationOutcome.NO_OPPORTUNITY)

    # NO_EVALUABLE_EVENTS : aucun candidat du tout.
    return response(RecommendationOutcome.NO_EVALUABLE_EVENTS)
