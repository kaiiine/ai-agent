"""Pipeline Advisor de bout en bout (pur domaine) : à partir d'un `AdaptedBatch`
déjà produit par l'adaptateur, enchaîne génération → éligibilité → ranking →
recommandation. Aucune I/O, aucun scan : c'est la glue que le CLE/CLI appelle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .candidate_generation import generate_candidates
from .combos import build_combos
from .combos.policy import ComboPolicy
from .domain.recommendations import RecommendationResponse
from .domain.requests import RecommendationRequest
from .input_adapter.schema import AdaptedBatch
from .policy import PolicyConfig, evaluate_candidates
from .policy import reason_codes
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
    combo_policy: ComboPolicy | None = None,
) -> RecommendationResponse:
    ranking_profile = ranking_profiles.get(request.ranking_profile)
    if ranking_profile is None:
        raise ValueError(f"profil de ranking non configuré : {request.ranking_profile}")

    candidates = generate_candidates(adapted_batch)
    policy_evaluations = evaluate_candidates(candidates, request, config=policy_config)
    ranking_result = rank(policy_evaluations, profile=ranking_profile)
    response = recommend(policy_evaluations, ranking_result, request,
                         sizing_profiles=sizing_profiles, caps_config=portfolio_caps)

    # allow_combos : le Combo Builder est appelé UNIQUEMENT si demandé. Les combos
    # admissibles sont évalués et classés mais NON misés (fork sizing COMBO, Lot 9) :
    # aucune PortfolioLine COMBO n'est inventée, un avertissement l'expose.
    if request.allow_combos and combo_policy is not None:
        combos, _ = build_combos(ranking_result.ranked, request, combo_policy)
        if combos.admissible:
            # Code STABLE (préfixe machine-readable) + explication humaine associée.
            note = (f"{reason_codes.COMBO_SIZING_NOT_AVAILABLE}: {len(combos.admissible)} combo(s) "
                    f"admissible(s) évalué(s) et classé(s) mais NON misé(s) (PortfolioLine.stake "
                    f"requis, aucun contrat de sizing combo) ; acceptation bookmaker non vérifiée")
            response = replace(response, warnings=tuple(response.warnings) + (note,))
    return response
