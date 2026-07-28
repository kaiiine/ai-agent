"""Eligibility / Policy (Lot 4) — ELIGIBLE / REVIEW_ONLY / REJECTED.

Vérifie la table de maturité, les filtres utilisateur, qualité/fraîcheur
(FRESHNESS_UNKNOWN ≠ STALE_ODDS), événement commencé, conflit d'identité,
contraintes de mise, EV basse, et des codes de rejet stables — seuils en config.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.advisor.domain.candidates import CandidateBet
from src.agents.quant.advisor.domain.enums import (
    CandidateStatus, MaturityPolicy, RiskProfile,
)
from src.agents.quant.advisor.domain.requests import OddsRange, RecommendationRequest
from src.agents.quant.advisor.policy import reason_codes as R
from src.agents.quant.advisor.policy.eligibility import (
    PolicyConfig, PolicyProfile, evaluate_candidates, evaluate_eligibility, load_policy_config,
)

_DEC = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
_KO = datetime(2026, 7, 29, 17, tzinfo=timezone.utc)       # futur / à venir

_PROFILE = PolicyProfile(
    min_expected_value_low=Decimal("0.01"), min_data_quality=Decimal("0.50"),
    min_freshness=Decimal("0.30"), min_stake=Decimal("0.20"))
_CONFIG = PolicyConfig(version="test", profiles={"BALANCED": _PROFILE})


def _candidate(**kw) -> CandidateBet:
    base = dict(
        candidate_id="c1", event_id="e1", sport="football",
        competition_id="competition:football:fra:ligue1", scheduled_at=_KO,
        bookmaker="winamax", market_id="winamax:e1:MATCH_WINNER",
        market_type="MATCH_WINNER", selection="home",
        bookmaker_odds=Decimal("2.10"), fair_probability=Decimal("0.50"),
        probability_low=Decimal("0.50"), probability_high=Decimal("0.50"),
        fair_odds=Decimal("2.00"), implied_probability=Decimal("0.4762"),
        expected_value_mean=Decimal("0.05"), expected_value_low=Decimal("0.05"),
        edge_mean=Decimal("0.02"), edge_low=Decimal("0.02"),
        model_version="m.v1", model_maturity="EXPERIMENTAL", calibration_score=None,
        data_quality=Decimal("1.0"), freshness_score=None, liquidity_score=None,
        max_stake=None, max_payout=None, is_boosted=False,
        participant_ids=("team:a", "team:b"), exposure_keys=frozenset({"event:e1"}),
        warnings=(), explanation_ref="expl:c1", source_decision_id=None)
    base.update(kw)
    return CandidateBet(**base)


def _request(**kw) -> RecommendationRequest:
    base = dict(
        request_id="r1", decision_time=_DEC, bankroll=Decimal("5"), currency="EUR",
        allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None,
        allowed_market_types=None, target_total_odds=OddsRange(Decimal("2.00"), Decimal("3.00")),
        max_total_stake=Decimal("5"), max_selections=2, max_portfolios=3,
        allow_singles=True, allow_combos=True, max_combo_legs=2,
        risk_profile=RiskProfile.BALANCED, maturity_policy=MaturityPolicy.INCLUDE_EXPERIMENTAL_FOR_REVIEW,
        ranking_profile="balanced_v1", excluded_event_ids=frozenset(),
        excluded_participant_ids=frozenset(), excluded_market_types=frozenset())
    base.update(kw)
    return RecommendationRequest(**base)


def _eval(candidate=None, request=None):
    return evaluate_eligibility(candidate or _candidate(), request or _request(), config=_CONFIG)


# ── Maturité ──────────────────────────────────────────────────────────────────
def test_supported_is_eligible_with_known_fresh_odds():
    ev = _eval(_candidate(model_maturity="SUPPORTED", freshness_score=Decimal("0.90")),
               _request(maturity_policy=MaturityPolicy.SUPPORTED_ONLY))
    assert ev.status is CandidateStatus.ELIGIBLE
    assert ev.policy_reasons == ()
    assert ev.ranking_score is None and ev.ranking_components == {}   # ranking = Lot 5


def test_experimental_is_review_only_under_include():
    ev = _eval()                                     # EXPERIMENTAL + INCLUDE + freshness None
    assert ev.status is CandidateStatus.REVIEW_ONLY
    assert R.EXPERIMENTAL_REVIEW_ONLY in ev.policy_reasons
    assert R.FRESHNESS_UNKNOWN in ev.policy_reasons  # fraîcheur inconnue signalée en revue


def test_experimental_rejected_under_supported_only():
    ev = _eval(request=_request(maturity_policy=MaturityPolicy.SUPPORTED_ONLY))
    assert ev.status is CandidateStatus.REJECTED
    assert ev.policy_reasons == (R.MODEL_NOT_SUPPORTED,)


def test_insufficient_data_rejected():
    ev = _eval(_candidate(model_maturity="INSUFFICIENT_DATA"))
    assert ev.status is CandidateStatus.REJECTED
    assert ev.policy_reasons == (R.MODEL_NOT_SUPPORTED,)


def test_unknown_maturity_fails_loud():
    with pytest.raises(ValueError):
        _eval(_candidate(model_maturity="WEIRD"))


# ── Filtres utilisateur ───────────────────────────────────────────────────────
def test_sport_filter():
    ev = _eval(request=_request(allowed_sports=frozenset({"tennis"})))
    assert ev.policy_reasons == (R.USER_FILTERED_SPORT,)


def test_competition_filter():
    ev = _eval(request=_request(allowed_competitions=frozenset({"competition:football:eng:pl"})))
    assert ev.policy_reasons == (R.USER_FILTERED_COMPETITION,)


def test_market_filter():
    ev = _eval(request=_request(allowed_market_types=frozenset({"OVER_UNDER"})))
    assert ev.policy_reasons == (R.USER_FILTERED_MARKET,)


def test_bookmaker_filter():
    ev = _eval(request=_request(allowed_bookmakers=frozenset({"betclic"})))
    assert ev.policy_reasons == (R.USER_FILTERED_BOOKMAKER,)


def test_excluded_event_and_participant():
    assert _eval(request=_request(excluded_event_ids=frozenset({"e1"}))).policy_reasons == (
        R.USER_EXCLUDED_EVENT,)
    assert _eval(request=_request(excluded_participant_ids=frozenset({"team:b"}))).policy_reasons == (
        R.USER_EXCLUDED_PARTICIPANT,)


# ── Validité / contraintes ────────────────────────────────────────────────────
def test_event_already_started_rejected():
    ev = _eval(_candidate(scheduled_at=datetime(2026, 7, 28, 11, tzinfo=timezone.utc)))  # avant decision_time
    assert ev.policy_reasons == (R.EVENT_ALREADY_STARTED,)


def test_identity_conflict_rejected():
    ev = _eval(_candidate(participant_ids=()))       # aucune identité résolue
    assert ev.policy_reasons == (R.IDENTITY_CONFLICT,)


def test_stake_limit_too_low():
    ev = _eval(_candidate(max_stake=Decimal("0.10")))  # < min_stake 0.20
    assert ev.policy_reasons == (R.STAKE_LIMIT_TOO_LOW,)


def test_boosted_not_supported_rejected():
    ev = _eval(_candidate(is_boosted=True))          # EXPERIMENTAL + boosté -> rejet
    assert ev.policy_reasons == (R.BOOSTED_MARKET_NOT_SUPPORTED,)


# ── Qualité / fraîcheur ───────────────────────────────────────────────────────
def test_low_data_quality_rejected():
    ev = _eval(_candidate(data_quality=Decimal("0.10")))  # < 0.50
    assert ev.policy_reasons == (R.LOW_DATA_QUALITY,)


def test_stale_odds_distinct_from_unknown():
    # Fraîcheur MESURÉE et insuffisante -> STALE_ODDS (≠ FRESHNESS_UNKNOWN).
    ev = _eval(_candidate(freshness_score=Decimal("0.10")))  # < min_freshness 0.30
    assert ev.policy_reasons == (R.STALE_ODDS,)
    assert R.FRESHNESS_UNKNOWN not in ev.policy_reasons


def test_freshness_unknown_rejected_under_supported_only():
    ev = _eval(_candidate(model_maturity="SUPPORTED"),
               _request(maturity_policy=MaturityPolicy.SUPPORTED_ONLY))  # freshness None
    assert ev.status is CandidateStatus.REJECTED
    assert ev.policy_reasons == (R.FRESHNESS_UNKNOWN,)


def test_unknown_freshness_downgrades_eligible_to_review():
    # SUPPORTED + INCLUDE mais fraîcheur inconnue -> jamais ELIGIBLE (non misable).
    ev = _eval(_candidate(model_maturity="SUPPORTED"))
    assert ev.status is CandidateStatus.REVIEW_ONLY
    assert ev.policy_reasons == (R.FRESHNESS_UNKNOWN,)


# ── EV basse (chemin ELIGIBLE seulement) ──────────────────────────────────────
def test_low_worst_case_ev_rejected():
    ev = _eval(_candidate(model_maturity="SUPPORTED", freshness_score=Decimal("0.90"),
                          expected_value_low=Decimal("0.00")),   # <= min_ev_low 0.01
               _request(maturity_policy=MaturityPolicy.SUPPORTED_ONLY))
    assert ev.status is CandidateStatus.REJECTED
    assert ev.policy_reasons == (R.LOW_WORST_CASE_EV,)


# ── Batch : une évaluation par candidat, indépendant de l'ordre ───────────────
def test_evaluate_candidates_one_per_candidate_order_independent():
    c1 = _candidate(candidate_id="c1", event_id="e1")
    c2 = _candidate(candidate_id="c2", event_id="e2", model_maturity="SUPPORTED",
                    freshness_score=Decimal("0.9"))
    req = _request(maturity_policy=MaturityPolicy.SUPPORTED_ONLY)
    a = {e.candidate.candidate_id: e.status for e in evaluate_candidates([c1, c2], req, config=_CONFIG)}
    b = {e.candidate.candidate_id: e.status for e in evaluate_candidates([c2, c1], req, config=_CONFIG)}
    assert a == b                                    # indépendant de l'ordre
    assert a["c1"] is CandidateStatus.REJECTED       # EXPERIMENTAL sous SUPPORTED_ONLY
    assert a["c2"] is CandidateStatus.ELIGIBLE


# ── Config ────────────────────────────────────────────────────────────────────
def test_default_config_loads_and_is_versioned():
    cfg = load_policy_config()
    assert cfg.version and {"CONSERVATIVE", "BALANCED", "AGGRESSIVE"} <= set(cfg.profiles)
    assert isinstance(cfg.profile_for(RiskProfile.BALANCED).min_expected_value_low, Decimal)


def test_unconfigured_profile_raises():
    with pytest.raises(ValueError):
        _CONFIG.profile_for(RiskProfile.CONSERVATIVE)   # absent de la config de test


def test_all_reason_codes_are_registered():
    # Tout code émis appartient à l'ensemble stable déclaré.
    emitted = set()
    for req in (_request(), _request(maturity_policy=MaturityPolicy.SUPPORTED_ONLY)):
        for c in (_candidate(), _candidate(is_boosted=True), _candidate(data_quality=Decimal("0.1"))):
            emitted.update(evaluate_eligibility(c, req, config=_CONFIG).policy_reasons)
    assert emitted <= R.ALL_REASON_CODES
