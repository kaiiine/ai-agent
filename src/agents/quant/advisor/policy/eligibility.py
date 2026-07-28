"""Politique d'éligibilité (PRD §11) — ELIGIBLE / REVIEW_ONLY / REJECTED.

Applique, dans l'ordre §11.1, les portes de décision et produit une
`CandidateEvaluation` (statut + `policy_reasons`) pour CHAQUE candidat (les
rejetés inclus, pour la traçabilité et le `rejection_summary`). Le ranking
(`ranking_score` / `ranking_components`) reste vide ici : c'est le Lot 5.

Aucun seuil métier codé en dur : tous viennent de `configs/advisor/`
(`PolicyConfig`), versionnés. `target_total_odds` n'est PAS une porte de rejet
(objectif souple, ADR-ADV-011) : il guide le ranking/portefeuille, pas
l'éligibilité."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from ..domain.candidates import CandidateBet, CandidateEvaluation
from ..domain.enums import CandidateStatus, MaturityPolicy, RiskProfile
from ..domain.money import require_unit_interval
from ..domain.requests import RecommendationRequest
from . import filters, reason_codes
from .maturity import maturity_decision

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "advisor" / "eligibility_policy.json"
)


@dataclass(frozen=True)
class PolicyProfile:
    min_expected_value_low: Decimal
    min_data_quality: Decimal
    min_freshness: Decimal
    min_stake: Decimal


@dataclass(frozen=True)
class PolicyConfig:
    version: str
    profiles: Mapping[str, PolicyProfile]

    def profile_for(self, risk_profile: RiskProfile) -> PolicyProfile:
        key = risk_profile.value
        profile = self.profiles.get(key)
        if profile is None:
            raise ValueError(f"profil de politique non configuré : {key}")
        return profile


def load_policy_config(path: pathlib.Path = _CONFIG_PATH) -> PolicyConfig:
    """Charge la config versionnée. Decimal via chaîne (aucun float)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = {
        name: PolicyProfile(
            min_expected_value_low=Decimal(p["min_expected_value_low"]),
            min_data_quality=Decimal(p["min_data_quality"]),
            min_freshness=Decimal(p["min_freshness"]),
            min_stake=Decimal(p["min_stake"]),
        )
        for name, p in data["profiles"].items()
    }
    config = PolicyConfig(version=data["version"], profiles=profiles)
    # Garde-fou : les seuils de config restent dans [0, 1] là où c'est attendu.
    for prof in profiles.values():
        require_unit_interval(prof.min_data_quality, "min_data_quality")
        require_unit_interval(prof.min_freshness, "min_freshness")
    return config


def _evaluation(candidate: CandidateBet, status: CandidateStatus,
                reasons: tuple[str, ...]) -> CandidateEvaluation:
    return CandidateEvaluation(candidate=candidate, status=status,
                               policy_reasons=reasons, ranking_score=None,
                               ranking_components={})


def _rejected(candidate: CandidateBet, reason: str) -> CandidateEvaluation:
    return _evaluation(candidate, CandidateStatus.REJECTED, (reason,))


def evaluate_eligibility(
    candidate: CandidateBet, request: RecommendationRequest, *, config: PolicyConfig,
) -> CandidateEvaluation:
    """Une décision d'éligibilité, portes dans l'ordre §11.1. Court-circuite au
    PREMIER rejet dur (raison unique déterministe) ; REVIEW_ONLY accumule ses
    raisons de revue."""
    profile = config.profile_for(request.risk_profile)

    # (1) Validité fondamentale : identité résolue, événement à venir.
    if not candidate.participant_ids:
        return _rejected(candidate, reason_codes.IDENTITY_CONFLICT)
    if candidate.scheduled_at <= request.decision_time:
        return _rejected(candidate, reason_codes.EVENT_ALREADY_STARTED)

    # (2-3) Filtres utilisateur + disponibilité bookmaker.
    filtered = filters.user_filter_rejection(candidate, request)
    if filtered is not None:
        return _rejected(candidate, filtered)

    # (4) Maturité du modèle -> statut de base (ou rejet).
    base_status, maturity_reason = maturity_decision(candidate.model_maturity, request.maturity_policy)
    if base_status is CandidateStatus.REJECTED:
        return _rejected(candidate, maturity_reason)
    review_reasons: list[str] = [] if maturity_reason is None else [maturity_reason]

    # (5) Politique de marché : une offre boostée n'est éligible que si SUPPORTED.
    if candidate.is_boosted and candidate.model_maturity != "SUPPORTED":
        return _rejected(candidate, reason_codes.BOOSTED_MARKET_NOT_SUPPORTED)

    # (6) Qualité des données.
    if candidate.data_quality < profile.min_data_quality:
        return _rejected(candidate, reason_codes.LOW_DATA_QUALITY)

    # (7) Fraîcheur : FRESHNESS_UNKNOWN (non mesurable) distinct de STALE_ODDS (mesurée insuffisante).
    if candidate.freshness_score is not None:
        if candidate.freshness_score < profile.min_freshness:
            return _rejected(candidate, reason_codes.STALE_ODDS)
    else:
        # Fraîcheur inconnue (Q1) : rejet sous SUPPORTED_ONLY. Sous INCLUDE, une offre
        # dont on ne peut vérifier la fraîcheur ne peut pas rester ELIGIBLE (donc
        # jamais misable) -> au plus REVIEW_ONLY, avec la raison signalée.
        if request.maturity_policy is MaturityPolicy.SUPPORTED_ONLY:
            return _rejected(candidate, reason_codes.FRESHNESS_UNKNOWN)
        if base_status is CandidateStatus.ELIGIBLE:
            base_status = CandidateStatus.REVIEW_ONLY
        review_reasons.append(reason_codes.FRESHNESS_UNKNOWN)

    # (8) Contraintes de mise (plafond bookmaker sous le minimum viable).
    if candidate.max_stake is not None and candidate.max_stake < profile.min_stake:
        return _rejected(candidate, reason_codes.STAKE_LIMIT_TOO_LOW)

    # (9) Statut final.
    if base_status is CandidateStatus.ELIGIBLE:
        # Le seuil d'EV ne gate QUE le chemin ELIGIBLE (modèle SUPPORTED).
        if candidate.expected_value_low <= profile.min_expected_value_low:
            return _rejected(candidate, reason_codes.LOW_WORST_CASE_EV)
        return _evaluation(candidate, CandidateStatus.ELIGIBLE, ())

    return _evaluation(candidate, CandidateStatus.REVIEW_ONLY, tuple(review_reasons))


def evaluate_candidates(
    candidates: Sequence[CandidateBet], request: RecommendationRequest, *, config: PolicyConfig,
) -> tuple[CandidateEvaluation, ...]:
    """Une `CandidateEvaluation` par candidat (rejetés inclus). Indépendant de
    l'ordre d'entrée : chaque candidat est évalué isolément."""
    return tuple(evaluate_eligibility(c, request, config=config) for c in candidates)
