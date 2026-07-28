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

from ..domain.candidates import CandidateEvaluation
from ..domain.enums import CandidateStatus, RecommendationOutcome
from ..domain.money import ZERO
from ..domain.recommendations import RecommendationResponse
from ..domain.requests import RecommendationRequest
from ..ranking.sort import RankingResult
from . import audit, simple
from .simple import SizingProfile


def _rejection_summary(rejected: Sequence[CandidateEvaluation]) -> dict[str, int]:
    return dict(Counter(reason for ev in rejected for reason in ev.policy_reasons))


def recommend(
    policy_evaluations: Sequence[CandidateEvaluation], ranking_result: RankingResult,
    request: RecommendationRequest, *, sizing_profiles: Mapping[str, SizingProfile],
) -> RecommendationResponse:
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

    # RECOMMENDED : meilleur ELIGIBLE misable.
    if ranking_result.ranked:
        top = ranking_result.ranked[0]
        sizing = sizing_profiles.get(request.risk_profile.value)
        if sizing is None:
            raise ValueError(f"profil de sizing non configuré : {request.risk_profile.value}")
        stake = simple.compute_single_stake(
            top.candidate, reliability=top.ranking_components["reliability_component"],
            bankroll=request.bankroll, max_total_stake=request.max_total_stake, sizing=sizing)
        if stake > ZERO:
            portfolio = simple.build_single_portfolio(top, stake, request)
            return response(RecommendationOutcome.RECOMMENDED, portfolios=(portfolio,),
                            review_candidates=review)

    # REVIEW_CANDIDATES : rien de misable mais des candidats à examiner.
    if review:
        return response(RecommendationOutcome.REVIEW_CANDIDATES, review_candidates=review)

    # NO_OPPORTUNITY : des candidats existaient, aucun retenu ni à examiner.
    if policy_evaluations or ranking_result.non_rankable:
        return response(RecommendationOutcome.NO_OPPORTUNITY)

    # NO_EVALUABLE_EVENTS : aucun candidat du tout.
    return response(RecommendationOutcome.NO_EVALUABLE_EVENTS)
