"""Combo Builder V1 (Lot 9) : construit, filtre, évalue et classe des combinés de
2 legs, de façon DÉTERMINISTE et PRUDENTE. Aucun moteur probabiliste sportif,
aucune hypothèse d'indépendance non structurellement justifiée.

Pipeline : top-K classés -> paires canoniques -> compatibilité -> dépendance ->
seuls INDEPENDENT_ENOUGH -> pricing mean/low -> filtre worst_case_ev >= min_combo_ev
-> ranking -> explication. `combo_id` = identité STRUCTURELLE des legs, indépendante
de la config, du pricing, de l'admission et de l'ordre d'entrée."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from ..domain.candidates import CandidateEvaluation
from ..domain.enums import DependencyStatus
from ..domain.requests import RecommendationRequest
from . import compatibility, dependency, pruning
from .policy import ComboPolicy
from .pricing import ComboPricing, price_combo

_INDEP_NOTE = (
    "INDEPENDENT_ENOUGH est un proxy STRUCTUREL (événements et participants "
    "disjoints), PAS une preuve d'indépendance."
)
_V1_LIMITATIONS = (
    "dépendances non détectées en V1 : contexte de compétition partagé, enjeux "
    "croisés de fin de saison, météo/conditions communes, effets de calendrier, "
    "facteurs externes multi-événements",
)
_BOOKMAKER_ACCEPTANCE_NOTE = (
    "l'acceptation réelle de cette combinaison par le bookmaker n'a pas été "
    "vérifiée avant exécution (donnée non exposée par les contrats en V1)"
)


@dataclass(frozen=True)
class ComboExplanation:
    summary: str
    why_legs: tuple[str, ...]
    dependency_note: str
    safety_margin: Decimal
    config_version: str
    joint_prob_mean_raw: Decimal | None
    joint_prob_low_raw: Decimal | None
    combined_prob_mean: Decimal | None
    combined_prob_low: Decimal | None
    expected_value: Decimal | None
    worst_case_ev: Decimal | None
    rejection_reason: str | None
    v1_limitations: tuple[str, ...]
    bookmaker_acceptance_note: str


@dataclass(frozen=True)
class ComboEvaluation:
    combo_id: str
    legs: tuple[CandidateEvaluation, CandidateEvaluation]   # ordre canonique (candidate_id trié)
    compatibility_reason: str | None
    dependency_status: DependencyStatus | None
    pricing: ComboPricing | None
    admissible: bool
    rejection_reason: str | None
    target_odds_match: bool
    min_leg_quality: Decimal | None


@dataclass(frozen=True)
class ComboResult:
    admissible: tuple[ComboEvaluation, ...]                 # classés
    rejected: tuple[ComboEvaluation, ...]


def combo_id(a: CandidateEvaluation, b: CandidateEvaluation) -> str:
    """Identité STRUCTURELLE : hash du tuple canonique (trié) des candidate_id.
    Indépendante de la config, du pricing, de l'admission, de l'ordre d'entrée."""
    ids = sorted((a.candidate.candidate_id, b.candidate.candidate_id))
    digest = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:24]
    return f"combo:{digest}"


def _explanation(legs, pricing, dep, rejection_reason, policy) -> ComboExplanation:
    return ComboExplanation(
        summary=f"combo 2 legs : {legs[0].candidate.candidate_id} + {legs[1].candidate.candidate_id}",
        why_legs=tuple(f"{leg.candidate.candidate_id} classé ELIGIBLE" for leg in legs),
        dependency_note=_INDEP_NOTE if dep is DependencyStatus.INDEPENDENT_ENOUGH
        else (f"paire refusée : {dep.value}" if dep is not None else "compatibilité non satisfaite"),
        safety_margin=policy.safety_margin, config_version=policy.config_version,
        joint_prob_mean_raw=pricing.joint_prob_mean_raw if pricing else None,
        joint_prob_low_raw=pricing.joint_prob_low_raw if pricing else None,
        combined_prob_mean=pricing.combined_prob_mean if pricing else None,
        combined_prob_low=pricing.combined_prob_low if pricing else None,
        expected_value=pricing.expected_value if pricing else None,
        worst_case_ev=pricing.worst_case_ev if pricing else None,
        rejection_reason=rejection_reason, v1_limitations=_V1_LIMITATIONS,
        bookmaker_acceptance_note=_BOOKMAKER_ACCEPTANCE_NOTE)


def evaluate_pair(
    a: CandidateEvaluation, b: CandidateEvaluation, request: RecommendationRequest,
    policy: ComboPolicy,
) -> tuple[ComboEvaluation, ComboExplanation]:
    legs = tuple(sorted((a, b), key=lambda e: e.candidate.candidate_id))
    cid = combo_id(a, b)

    def result(compat, dep, pricing, admissible, reason, target_match, min_quality):
        combo = ComboEvaluation(
            combo_id=cid, legs=legs, compatibility_reason=compat, dependency_status=dep,
            pricing=pricing, admissible=admissible, rejection_reason=reason,
            target_odds_match=target_match, min_leg_quality=min_quality)
        return combo, _explanation(legs, pricing, dep, reason, policy)

    # (1) Compatibilité — AVANT toute classification de dépendance.
    compat = compatibility.check_compatibility(legs[0], legs[1], request)
    if compat is not None:
        return result(compat, None, None, False, compat, False, None)

    # (2) Dépendance — seul INDEPENDENT_ENOUGH poursuit.
    dep = dependency.classify(legs[0].candidate, legs[1].candidate)
    min_quality = min(legs[0].candidate.data_quality, legs[1].candidate.data_quality)
    if dep is not DependencyStatus.INDEPENDENT_ENOUGH:
        return result(None, dep, None, False, dep.value, False, min_quality)

    # (3) Pricing mean/low avec marge de sécurité commune.
    pricing = price_combo([legs[0].candidate, legs[1].candidate], policy.safety_margin)
    target = request.target_total_odds
    target_match = target is not None and target.minimum <= pricing.combined_odds <= target.maximum

    # (4) Admission fondée sur le SCÉNARIO BAS.
    if pricing.worst_case_ev < policy.min_combo_ev:
        return result(None, dep, pricing, False, "LOW_WORST_CASE_EV", target_match, min_quality)
    return result(None, dep, pricing, True, None, target_match, min_quality)


def build_combos(
    ranked: Sequence[CandidateEvaluation], request: RecommendationRequest, policy: ComboPolicy,
) -> tuple[ComboResult, dict[str, ComboExplanation]]:
    """Combos admissibles (classés) + rejetés, et l'explication de chaque combo
    (par combo_id). N'est appelé que si `allow_combos=True` (garde côté appelant)."""
    top_k = list(ranked)[:policy.top_k]
    admissible: list[ComboEvaluation] = []
    rejected: list[ComboEvaluation] = []
    explanations: dict[str, ComboExplanation] = {}

    for a, b in pruning.canonical_pairs(top_k):
        combo, expl = evaluate_pair(a, b, request, policy)
        explanations[combo.combo_id] = expl
        (admissible if combo.admissible else rejected).append(combo)

    return ComboResult(admissible=pruning.rank_combos(admissible), rejected=tuple(rejected)), explanations


class ComboSizingRequired(NotImplementedError):
    """FORK money-sensitive (Lot 9). `PortfolioLine.stake` est non optionnel, mais
    aucun contrat de sizing COMBO validé n'existe : on ne transforme JAMAIS un combo
    admissible en `PortfolioLine` avec une mise improvisée. Décision dédiée requise
    (fiabilité de la proba jointe, rôle de la marge dans le sizing, caps combo,
    exposition des legs, interaction avec les allocations SINGLE, corrélation
    résiduelle). Cf. current-state §10.6 et le stop du Lot 9."""


def to_portfolio_line(combo: ComboEvaluation):
    """Frontière atteinte : refuse d'inventer une mise. Lève toujours tant
    qu'aucun contrat de sizing COMBO n'est validé."""
    raise ComboSizingRequired(
        f"combo {combo.combo_id} admissible mais non transformable en PortfolioLine "
        f"faute de contrat de sizing COMBO validé")
