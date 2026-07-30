"""Pipeline Advisor de bout en bout (pur domaine) : génération → éligibilité →
ranking → recommandation (+ combos si demandé). Produit la `RecommendationResponse`
ET, EN PARALLÈLE, une `AuditTrace` des décisions intermédiaires (Lot 10 §14) — la
réponse métier n'est jamais polluée par l'audit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from .candidate_generation import generate_candidates
from .combos import build_combos
from .combos.builder import ComboResult
from .combos.policy import ComboPolicy
from .domain.candidates import CandidateEvaluation
from .domain.recommendations import RecommendationResponse
from .domain.requests import RecommendationRequest
from .input_adapter.schema import AdaptedBatch
from .policy import PolicyConfig, evaluate_candidates
from .portfolio.constraints import PortfolioCaps
from .ranking import RankingProfile, rank
from .recommendation import recommend
from .recommendation.simple import SizingProfile


@dataclass(frozen=True)
class AuditTrace:
    policy_evaluations: Sequence[CandidateEvaluation]
    ranked_evaluations: Sequence[CandidateEvaluation]
    combo_builder_invoked: bool
    combo_result: ComboResult | None
    combo_policy: ComboPolicy | None


@dataclass(frozen=True)
class PipelineRunResult:
    recommendation: RecommendationResponse
    trace: AuditTrace


def run_pipeline(
    adapted_batch: AdaptedBatch, request: RecommendationRequest, *,
    policy_config: PolicyConfig,
    ranking_profiles: Mapping[str, RankingProfile],
    sizing_profiles: Mapping[str, SizingProfile],
    portfolio_caps: Mapping[str, PortfolioCaps],
    combo_policy: ComboPolicy | None = None,
) -> PipelineRunResult:
    ranking_profile = ranking_profiles.get(request.ranking_profile)
    if ranking_profile is None:
        raise ValueError(f"profil de ranking non configuré : {request.ranking_profile}")

    candidates = generate_candidates(adapted_batch)
    policy_evaluations = evaluate_candidates(candidates, request, config=policy_config)
    ranking_result = rank(policy_evaluations, profile=ranking_profile)

    # allow_combos : builder appelé UNIQUEMENT si demandé, AVANT la recommandation
    # pour que les combos admissibles entrent dans l'allocation (ADR-ADV-014).
    invoked = False
    combo_result: ComboResult | None = None
    admissible_combos: tuple = ()
    if request.allow_combos and combo_policy is not None:
        invoked = True
        combo_result, _ = build_combos(ranking_result.ranked, request, combo_policy)
        admissible_combos = combo_result.admissible

    response = recommend(policy_evaluations, ranking_result, request,
                         sizing_profiles=sizing_profiles, caps_config=portfolio_caps,
                         combos=admissible_combos)

    # Combos admissibles : sizés/matérialisés dans le primaire (si caps le permettent).
    # Note d'audit sur l'acceptation bookmaker (jamais un blocage) — le sizing EST dispo.
    if admissible_combos:
        note = (f"combos: {len(admissible_combos)} admissible(s) évalué(s) et sizé(s) "
                f"(ADR-ADV-014) ; acceptation bookmaker non vérifiée (donnée non exposée en V1)")
        response = replace(response, warnings=tuple(response.warnings) + (note,))

    trace = AuditTrace(
        policy_evaluations=tuple(policy_evaluations), ranked_evaluations=ranking_result.ranked,
        combo_builder_invoked=invoked, combo_result=combo_result, combo_policy=combo_policy)
    return PipelineRunResult(recommendation=response, trace=trace)
