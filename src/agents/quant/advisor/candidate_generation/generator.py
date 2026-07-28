"""Candidate Generator (PRD §10) — normalise chaque `AdaptedEvaluation` en
`CandidateBet`.

Ne décide PAS encore de l'éligibilité (Lot 4) ni du ranking (Lot 5). Ne crée
AUCUNE donnée sportive : il ne fait que dériver les champs autorisés (§10.2) à
partir de nombres déjà validés, construire un id stable, et attacher l'identité
et les clés d'exposition. Une métrique absente n'est jamais remplacée par une
valeur inventée (scores None restent None ; plafonds bookmaker non exposés
restent None — Vague 2)."""

from __future__ import annotations

from ..domain.candidates import CandidateBet
from ..input_adapter.schema import AdaptedBatch, AdaptedEvaluation
from .exposure_keys import exposure_keys_for
from .normalization import (
    edge,
    expected_value,
    fair_odds_from_probability,
    stable_candidate_id,
)


def candidate_from_evaluation(adapted: AdaptedEvaluation) -> CandidateBet:
    """Un `CandidateBet` à partir d'une évaluation adaptée. Lève si les métriques
    de valeur sont absentes (offre boostée / non évaluée : traitement Vague 2) —
    jamais de métrique fabriquée. L'identité temporelle du candidat vient de
    `observed_at` (l'offre), pas d'un instant de requête."""
    if adapted.implied_probability_raw is None or adapted.no_vig_probability is None:
        raise ValueError(
            f"métriques de valeur absentes pour {adapted.selection} "
            f"(offre boostée / non évaluée) — pas de candidat de valeur en V1")

    implied = adapted.implied_probability_raw
    no_vig = adapted.no_vig_probability
    candidate_id = stable_candidate_id(
        bookmaker=adapted.bookmaker, event_id=adapted.event_id,
        market_id=adapted.market_id, selection=adapted.selection,
        model_version=adapted.model_version, observed_at=adapted.observed_at)

    return CandidateBet(
        candidate_id=candidate_id,
        event_id=adapted.event_id,
        sport=adapted.sport,
        competition_id=adapted.competition_id,
        scheduled_at=adapted.scheduled_at,
        bookmaker=adapted.bookmaker,
        market_id=adapted.market_id,
        market_type=adapted.market_type,
        selection=adapted.selection,
        bookmaker_odds=adapted.bookmaker_odds,
        fair_probability=adapted.fair_probability,
        probability_low=adapted.probability_low,
        probability_high=adapted.probability_high,
        fair_odds=fair_odds_from_probability(adapted.fair_probability),
        implied_probability=implied,                         # implicite BRUTE (bookmaker), propagée
        expected_value_mean=expected_value(adapted.fair_probability, adapted.bookmaker_odds),
        expected_value_low=expected_value(adapted.probability_low, adapted.bookmaker_odds),
        edge_mean=edge(adapted.fair_probability, no_vig),     # définition moteur : fair − no_vig
        edge_low=edge(adapted.probability_low, no_vig),
        model_version=adapted.model_version,
        model_maturity=adapted.model_maturity,               # jamais rehaussée
        calibration_score=adapted.calibration_score,         # None : jamais 0
        data_quality=adapted.data_quality,
        freshness_score=adapted.freshness_score,             # None = FRESHNESS_UNKNOWN
        liquidity_score=adapted.liquidity_score,             # None : non exposé
        max_stake=None,                                      # plafond non exposé (Vague 2)
        max_payout=None,                                     # plafond non exposé (Vague 2)
        is_boosted=adapted.is_boosted,                       # statut préservé
        participant_ids=adapted.participant_ids,
        exposure_keys=exposure_keys_for(
            event_id=adapted.event_id, competition_id=adapted.competition_id,
            market_type=adapted.market_type, bookmaker=adapted.bookmaker,
            participant_ids=adapted.participant_ids),
        warnings=adapted.warnings,                           # préservés (aucun supprimé)
        explanation_ref=f"expl:{candidate_id}",
        source_decision_id=adapted.source_decision_id,       # None (Q5) : jamais inventé
    )


def generate_candidates(batch: AdaptedBatch) -> tuple[CandidateBet, ...]:
    """Tous les candidats d'un batch adapté. Ordre d'entrée préservé
    (déterministe) ; l'identité (candidate_id) ne dépend que de l'offre observée,
    jamais de l'ordre ni du decision_time. L'indépendance à l'ordre du CLASSEMENT
    est garantie plus tard par le Ranking (Lot 5)."""
    return tuple(candidate_from_evaluation(ev) for ev in batch.evaluations)
