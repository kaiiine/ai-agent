"""Contrats de domaine Advisor (Lot 1) — invariants + Decimal + round-trip JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.advisor.domain.candidates import CandidateBet, CandidateEvaluation
from src.agents.quant.advisor.domain.enums import (
    CandidateStatus, LineType, MaturityPolicy, RecommendationOutcome, RiskProfile,
)
from src.agents.quant.advisor.domain.portfolios import (
    BetLeg, PortfolioExplanation, PortfolioLine, RecommendationPortfolio,
)
from src.agents.quant.advisor.domain.recommendations import RecommendationResponse
from src.agents.quant.advisor.domain.requests import OddsRange, RecommendationRequest
from src.agents.quant.advisor.domain import serialization

_T = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)


def _request(**kw):
    base = dict(
        request_id="r1", decision_time=_T, bankroll=Decimal("5"), currency="EUR",
        allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None, allowed_market_types=None,
        target_total_odds=OddsRange(Decimal("2.00"), Decimal("3.00")),
        max_total_stake=Decimal("5"), max_selections=2, max_portfolios=3,
        allow_singles=True, allow_combos=True, max_combo_legs=2,
        risk_profile=RiskProfile.BALANCED, maturity_policy=MaturityPolicy.SUPPORTED_ONLY,
        ranking_profile="balanced_v1",
        excluded_event_ids=frozenset(), excluded_participant_ids=frozenset(), excluded_market_types=frozenset(),
    )
    base.update(kw)
    return RecommendationRequest(**base)


def _candidate(**kw):
    base = dict(
        candidate_id="c1", event_id="e1", sport="football", competition_id="competition:football:fra:ligue1",
        scheduled_at=_T, bookmaker="winamax", market_id="winamax:e1:MATCH_WINNER",
        market_type="MATCH_WINNER", selection="home",
        bookmaker_odds=Decimal("2.10"), fair_probability=Decimal("0.50"),
        probability_low=Decimal("0.50"), probability_high=Decimal("0.50"),
        fair_odds=Decimal("2.00"), implied_probability=Decimal("0.4762"),
        expected_value_mean=Decimal("0.05"), expected_value_low=Decimal("0.05"),
        edge_mean=Decimal("0.02"), edge_low=Decimal("0.02"),
        model_version="m.v0", model_maturity="EXPERIMENTAL", calibration_score=None,
        data_quality=Decimal("1.0"), freshness_score=None, liquidity_score=None,
        max_stake=None, max_payout=None, is_boosted=False,
        participant_ids=("team:a", "team:b"), exposure_keys=frozenset({"event:e1"}),
        warnings=("freshness_unavailable",), explanation_ref="expl:c1", source_decision_id=None,
    )
    base.update(kw)
    return CandidateBet(**base)


# ── RecommendationRequest ─────────────────────────────────────────────────────
def test_bankroll_must_be_positive():
    with pytest.raises(ValueError):
        _request(bankroll=Decimal("0"))


def test_max_stake_not_above_bankroll():
    with pytest.raises(ValueError):
        _request(bankroll=Decimal("5"), max_total_stake=Decimal("6"))


def test_max_selections_at_least_one():
    with pytest.raises(ValueError):
        _request(max_selections=0)


def test_max_combo_legs_when_combos_enabled():
    with pytest.raises(ValueError):
        _request(allow_combos=True, max_combo_legs=1)
    assert _request(allow_combos=False, max_combo_legs=1)   # ignoré si combos désactivés


def test_target_odds_inverted_rejected():
    with pytest.raises(ValueError):
        OddsRange(Decimal("3.00"), Decimal("2.00"))


def test_odds_range_minimum_must_exceed_one():
    with pytest.raises(ValueError):
        OddsRange(Decimal("1.00"), Decimal("2.00"))


def test_amounts_reject_float():
    with pytest.raises(TypeError):
        _request(bankroll=5.0)          # float interdit (ADV-NFR-010)


def test_unknown_enum_rejected():
    with pytest.raises(TypeError):
        _request(risk_profile="BALANCED")   # string au lieu d'enum


def test_decision_time_must_be_timezone_aware():
    with pytest.raises(ValueError):
        _request(decision_time=datetime(2026, 7, 28, 12))   # naïf


# ── CandidateBet ──────────────────────────────────────────────────────────────
def test_probability_interval_ordering():
    with pytest.raises(ValueError):
        _candidate(probability_low=Decimal("0.60"), fair_probability=Decimal("0.50"),
                   probability_high=Decimal("0.50"))


def test_fair_probability_out_of_bounds():
    with pytest.raises(ValueError):
        _candidate(fair_probability=Decimal("1.5"), probability_low=Decimal("0.5"),
                   probability_high=Decimal("1.5"))


def test_bookmaker_odds_must_exceed_one():
    with pytest.raises(ValueError):
        _candidate(bookmaker_odds=Decimal("1.00"))


def test_normalized_scores_within_unit_interval():
    with pytest.raises(ValueError):
        _candidate(data_quality=Decimal("1.5"))


def test_freshness_none_is_allowed_never_forced_to_zero():
    c = _candidate(freshness_score=None)
    assert c.freshness_score is None            # jamais converti en 0 (ADV-FR-041)


def test_candidate_amounts_reject_float():
    with pytest.raises(TypeError):
        _candidate(bookmaker_odds=2.10)         # float interdit


# ── PortfolioLine ─────────────────────────────────────────────────────────────
def _leg(bk="winamax", cid="c1"):
    return BetLeg(candidate_id=cid, event_id="e1", market_id="m1", selection="home", bookmaker=bk, odds=Decimal("2.0"))


def test_combo_must_use_single_bookmaker():
    with pytest.raises(ValueError):
        PortfolioLine("l1", LineType.COMBO, "winamax",
                      (_leg("winamax"), _leg("betclic", "c2")), Decimal("1"), Decimal("4.0"),
                      Decimal("0.25"), Decimal("0.0"), Decimal("0.0"), None)


def test_single_line_has_exactly_one_leg():
    with pytest.raises(ValueError):
        PortfolioLine("l1", LineType.SINGLE, "winamax", (_leg(), _leg(cid="c2")),
                      Decimal("1"), Decimal("4.0"), Decimal("0.25"), Decimal("0.0"), Decimal("0.0"), None)


# ── RecommendationResponse ────────────────────────────────────────────────────
def test_recommended_requires_portfolio():
    with pytest.raises(ValueError):
        RecommendationResponse("r1", _T, RecommendationOutcome.RECOMMENDED, (), (), {}, (), "a1")


def test_no_opportunity_carries_no_portfolio():
    resp = RecommendationResponse("r1", _T, RecommendationOutcome.NO_OPPORTUNITY, (), (), {}, (), "a1")
    assert resp.outcome is RecommendationOutcome.NO_OPPORTUNITY


# ── CandidateEvaluation ───────────────────────────────────────────────────────
def test_candidate_evaluation_typing():
    ev = CandidateEvaluation(_candidate(), CandidateStatus.REVIEW_ONLY, ("EXPERIMENTAL_REVIEW_ONLY",),
                             None, {"value_component": Decimal("0.4")})
    assert ev.status is CandidateStatus.REVIEW_ONLY


# ── Sérialisation JSON stable + round-trip ────────────────────────────────────
def test_request_json_roundtrip():
    req = _request(allowed_sports=frozenset({"football", "tennis"}),
                   excluded_event_ids=frozenset({"e9", "e8"}))
    assert serialization.request_from_json(serialization.to_json(req)) == req


def test_json_is_stable_and_decimal_is_string():
    req = _request()
    j1, j2 = serialization.to_json(req), serialization.to_json(req)
    assert j1 == j2                              # déterministe
    assert '"bankroll": "5"' in j1               # Decimal en chaîne, jamais float
    assert "5.0" not in j1                        # aucun float résiduel


# ── Sérialisation STRUCTURELLE des contrats riches (Lot 1, sans from_json) ─────
def _explanation():
    return PortfolioExplanation("résumé", {"l1": ("value",)}, {"l1": ("kelly",)},
                                ("alt1",), ("risk1",), ("EXPERIMENTAL",))


def _line():
    leg = BetLeg("c1", "e1", "winamax:e1:MATCH_WINNER", "home", "winamax", Decimal("2.10"))
    return PortfolioLine("l1", LineType.SINGLE, "winamax", (leg,), Decimal("1"), Decimal("2.10"),
                         Decimal("0.50"), Decimal("0.05"), Decimal("0.05"), None)


def _portfolio():
    return RecommendationPortfolio(
        "p1", "r1", "balanced_v1", (_line(),), Decimal("1"), Decimal("4"),
        Decimal("2.10"), Decimal("1.10"), Decimal("0.10"), Decimal("0.20"),
        True, Decimal("0.70"), (), _explanation())


def _evaluation():
    return CandidateEvaluation(_candidate(), CandidateStatus.REVIEW_ONLY,
                               ("EXPERIMENTAL_REVIEW_ONLY",), Decimal("0.40"),
                               {"value_component": Decimal("0.40")})


def test_candidate_bet_to_json_structure():
    data = json.loads(serialization.to_json(_candidate()))
    assert isinstance(data["bookmaker_odds"], str) and data["bookmaker_odds"] == "2.10"   # Decimal->str
    assert data["freshness_score"] is None and data["source_decision_id"] is None          # null, jamais 0
    assert data["is_boosted"] is False
    assert data["participant_ids"] == ["team:a", "team:b"]        # tuple -> list
    assert data["exposure_keys"] == ["event:e1"]                  # frozenset -> list déterministe
    assert isinstance(data["fair_probability"], str)             # aucun float
    assert serialization.to_json(_candidate()) == serialization.to_json(_candidate())     # déterministe


def test_recommendation_portfolio_to_json_structure():
    data = json.loads(serialization.to_json(_portfolio()))
    assert isinstance(data["total_stake"], str) and data["total_stake"] == "1"
    assert data["lines"][0]["line_type"] == "SINGLE"             # enum -> valeur canonique
    assert data["lines"][0]["legs"][0]["odds"] == "2.10"        # Decimal imbriqué -> str
    assert isinstance(data["explanation"]["selection_reasons"], dict)   # Mapping
    assert data["explanation"]["selection_reasons"]["l1"] == ["value"]  # tuple imbriqué -> list
    assert data["target_odds_match"] is True
    assert serialization.to_json(_portfolio()) == serialization.to_json(_portfolio())


def test_recommendation_response_to_json_structure():
    resp = RecommendationResponse("r1", _T, RecommendationOutcome.REVIEW_CANDIDATES, (),
                                  (_evaluation(),), {"MODEL_NOT_SUPPORTED": 3}, ("w1",), "audit1")
    data = json.loads(serialization.to_json(resp))
    assert data["outcome"] == "REVIEW_CANDIDATES"               # enum -> valeur
    assert data["portfolios"] == []                             # tuple vide -> []
    assert data["rejection_summary"] == {"MODEL_NOT_SUPPORTED": 3}
    # imbrication profonde correctement représentée
    ev = data["review_candidates"][0]
    assert ev["status"] == "REVIEW_ONLY"
    assert ev["candidate"]["bookmaker_odds"] == "2.10"
    assert isinstance(ev["ranking_components"]["value_component"], str)   # Decimal imbriqué -> str
    assert serialization.to_json(resp) == serialization.to_json(resp)     # déterministe
