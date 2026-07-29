"""Pipeline Advisor de bout en bout (pur domaine) : à partir d'un `AdaptedBatch`
déjà produit par l'adaptateur, enchaîne génération → éligibilité → ranking →
recommandation. Aucune I/O, aucun scan : c'est la glue que le CLE/CLI appelle."""

from __future__ import annotations

from collections.abc import Mapping

from .candidate_generation import generate_candidates
from .domain.recommendations import RecommendationResponse
from .domain.requests import RecommendationRequest
from .input_adapter.schema import AdaptedBatch
from .policy import PolicyConfig, evaluate_candidates
from .portfolio.constraints import PortfolioCaps
from .ranking import RankingProfile, rank
from .recommendation import recommend
from .recommendation.simple import SizingProfile


def run_pipeline(
    adapted_batch: AdaptedBatch, request: RecommendationRequest, *,
    policy_config: PolicyConfig,
    ranking_profiles: Mapping[str, RankingProfile],
    sizing_profiles: Mapping[str, SizingProfile],
    portfolio_caps: Mapping[str, PortfolioCaps],
) -> RecommendationResponse:
    ranking_profile = ranking_profiles.get(request.ranking_profile)
    if ranking_profile is None:
        raise ValueError(f"profil de ranking non configuré : {request.ranking_profile}")

    candidates = generate_candidates(adapted_batch)
    policy_evaluations = evaluate_candidates(candidates, request, config=policy_config)
    ranking_result = rank(policy_evaluations, profile=ranking_profile)
    return recommend(policy_evaluations, ranking_result, request,
                     sizing_profiles=sizing_profiles, caps_config=portfolio_caps)
