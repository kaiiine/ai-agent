"""Recommandation simple (Lot 6, ADR-ADV-007 tranche SINGLE). Fixtures ELIGIBLE/
SUPPORTED (aucun modèle réel SUPPORTED en V1).

Couvre : meilleur ELIGIBLE -> RECOMMENDED, review-only -> pas de mise, aucun
candidat -> NO_EVALUABLE_EVENTS, tous rejetés -> NO_OPPORTUNITY, bornes de mise
(bankroll/max_total_stake/max_stake/max_payout), None jamais 0, Kelly<=0 -> 0,
bankroll non saturée, déterminisme, audit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.agents.quant.advisor.domain.candidates import CandidateBet, CandidateEvaluation
from src.agents.quant.advisor.domain.enums import (
    CandidateStatus, LineType, MaturityPolicy, RecommendationOutcome, RiskProfile,
)
from src.agents.quant.advisor.domain.money import ONE
from src.agents.quant.advisor.domain.requests import OddsRange, RecommendationRequest
from src.agents.quant.advisor.policy import reason_codes as R
from src.agents.quant.advisor.portfolio import load_portfolio_caps
from src.agents.quant.advisor.ranking import load_ranking_profiles, rank
from src.agents.quant.advisor.ranking.sort import RankingResult
from src.agents.quant.advisor.recommendation import (
    build_audit_record, compute_single_stake, load_sizing_profiles, recommend,
)

_KO = datetime(2026, 8, 1, 17, tzinfo=timezone.utc)
_DEC = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
_RANK = load_ranking_profiles()["balanced_v1"]
_SIZING = load_sizing_profiles()
_SIZE_BAL = _SIZING["BALANCED"]
_CAPS = load_portfolio_caps()


def _cand(cid="c1", event="e1", odds=Decimal("2.10"), p_low=Decimal("0.55"),
          maturity="SUPPORTED", calibration=None, max_stake=None, max_payout=None,
          data_quality=Decimal("1.0")) -> CandidateBet:
    low = p_low
    high = p_low + Decimal("0.05")
    fair = (low + high) / 2
    return CandidateBet(
        candidate_id=cid, event_id=event, sport="football", competition_id="comp:1",
        scheduled_at=_KO, bookmaker="winamax", market_id="m", market_type="MATCH_WINNER",
        selection="home", bookmaker_odds=odds, fair_probability=fair,
        probability_low=low, probability_high=high, fair_odds=Decimal("1.90"),
        implied_probability=Decimal("0.4762"),
        expected_value_mean=fair * odds - ONE, expected_value_low=low * odds - ONE,
        edge_mean=Decimal("0.05"), edge_low=Decimal("0.03"), model_version="m.v1",
        model_maturity=maturity, calibration_score=calibration, data_quality=data_quality,
        freshness_score=Decimal("0.90"), liquidity_score=None, max_stake=max_stake,
        max_payout=max_payout, is_boosted=False, participant_ids=("team:a", "team:b"),
        exposure_keys=frozenset({f"event:{event}"}), warnings=(),
        explanation_ref="expl", source_decision_id=None)


def _elig(cand):
    return CandidateEvaluation(cand, CandidateStatus.ELIGIBLE, (), None, {})


def _request(**kw):
    base = dict(
        request_id="r1", decision_time=_DEC, bankroll=Decimal("100"), currency="EUR",
        allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None,
        allowed_market_types=None, target_total_odds=OddsRange(Decimal("2.00"), Decimal("3.00")),
        max_total_stake=Decimal("100"), max_selections=2, max_portfolios=3,
        allow_singles=True, allow_combos=False, max_combo_legs=2,
        risk_profile=RiskProfile.BALANCED, maturity_policy=MaturityPolicy.SUPPORTED_ONLY,
        ranking_profile="balanced_v1", excluded_event_ids=frozenset(),
        excluded_participant_ids=frozenset(), excluded_market_types=frozenset())
    base.update(kw)
    return RecommendationRequest(**base)


def _recommend(policy_evals, request=None):
    req = request or _request()
    ranked = rank([e for e in policy_evals if e.status is CandidateStatus.ELIGIBLE], profile=_RANK)
    return recommend(policy_evals, ranked, req, sizing_profiles=_SIZING, caps_config=_CAPS)


# ── Mapping des outcomes ──────────────────────────────────────────────────────
def test_best_eligible_is_recommended():
    a = _elig(_cand("a", "e1", p_low=Decimal("0.58")))       # meilleur EV
    b = _elig(_cand("b", "e2", p_low=Decimal("0.53")))
    resp = _recommend([a, b])
    assert resp.outcome is RecommendationOutcome.RECOMMENDED
    assert len(resp.portfolios) == 1
    line = resp.portfolios[0].lines[0]
    assert line.line_type is LineType.SINGLE and line.legs[0].candidate_id == "a"
    assert resp.portfolios[0].total_stake > 0


def test_review_only_produces_no_stake():
    review = CandidateEvaluation(_cand("x", maturity="EXPERIMENTAL"),
                                 CandidateStatus.REVIEW_ONLY, (R.EXPERIMENTAL_REVIEW_ONLY,), None, {})
    resp = _recommend([review])
    assert resp.outcome is RecommendationOutcome.REVIEW_CANDIDATES
    assert resp.portfolios == ()                              # aucune mise
    assert resp.review_candidates[0].candidate.candidate_id == "x"


def test_no_evaluable_events():
    resp = recommend([], RankingResult((), ()), _request(), sizing_profiles=_SIZING, caps_config=_CAPS)
    assert resp.outcome is RecommendationOutcome.NO_EVALUABLE_EVENTS
    assert resp.portfolios == () and resp.review_candidates == ()


def test_all_rejected_is_no_opportunity():
    rej = CandidateEvaluation(_cand("x"), CandidateStatus.REJECTED,
                              (R.LOW_DATA_QUALITY,), None, {})
    resp = _recommend([rej])
    assert resp.outcome is RecommendationOutcome.NO_OPPORTUNITY
    assert resp.rejection_summary == {R.LOW_DATA_QUALITY: 1}


# ── Bornes de mise ────────────────────────────────────────────────────────────
def test_stake_capped_by_max_total_stake():
    resp = _recommend([_elig(_cand("a"))], _request(max_total_stake=Decimal("2")))
    stake = resp.portfolios[0].total_stake
    assert stake == Decimal("2") and stake <= Decimal("100")


def test_stake_capped_by_candidate_max_stake():
    resp = _recommend([_elig(_cand("a", max_stake=Decimal("1.5")))])
    assert resp.portfolios[0].total_stake == Decimal("1.5")


def test_max_payout_respected():
    c = _cand("a", odds=Decimal("2.10"), max_payout=Decimal("3.0"))
    resp = _recommend([_elig(c)])
    stake = resp.portfolios[0].total_stake
    assert stake * Decimal("2.10") <= Decimal("3.0")         # gain plafonné


def test_none_caps_never_become_zero():
    # Aucun plafond exposé -> mise > 0 (jamais convertie en 0).
    stake = compute_single_stake(
        _cand("a", max_stake=None, max_payout=None), reliability=Decimal("0.60"),
        bankroll=Decimal("100"), max_total_stake=None, sizing=_SIZE_BAL)
    assert stake > 0


def test_kelly_non_positive_gives_no_stake():
    # EV_low <= 0 (p_low*odds <= 1) -> aucune mise.
    stake = compute_single_stake(
        _cand("a", odds=Decimal("2.10"), p_low=Decimal("0.45")), reliability=Decimal("0.60"),
        bankroll=Decimal("100"), max_total_stake=None, sizing=_SIZE_BAL)
    assert stake == 0


def test_non_supported_gives_no_stake():
    stake = compute_single_stake(
        _cand("a", maturity="EXPERIMENTAL"), reliability=Decimal("0.60"),
        bankroll=Decimal("100"), max_total_stake=None, sizing=_SIZE_BAL)
    assert stake == 0                                        # BE-FR-011


def test_bankroll_not_fully_used():
    resp = _recommend([_elig(_cand("a"))])
    pf = resp.portfolios[0]
    assert pf.total_stake < Decimal("100")
    assert pf.unallocated_bankroll == Decimal("100") - pf.total_stake
    assert pf.unallocated_bankroll > 0


# ── Déterminisme / audit ──────────────────────────────────────────────────────
def test_same_input_same_recommendation():
    evals = [_elig(_cand("a", p_low=Decimal("0.58"))), _elig(_cand("b", "e2"))]
    assert _recommend(evals) == _recommend(evals)            # réponse identique (stake, audit, etc.)


def test_audit_generated_and_deterministic():
    resp = _recommend([_elig(_cand("a"))])
    assert resp.audit_id.startswith("audit:")
    record = build_audit_record(_request(), resp, ranking_profile_name="balanced_v1")
    assert record["audit_id"] == resp.audit_id
    assert record["outcome"] == "RECOMMENDED" and record["n_portfolios"] == 1


def test_review_candidates_and_rejections_carried_when_recommended():
    a = _elig(_cand("a", p_low=Decimal("0.58")))
    review = CandidateEvaluation(_cand("r", "e2", maturity="EXPERIMENTAL"),
                                 CandidateStatus.REVIEW_ONLY, (R.EXPERIMENTAL_REVIEW_ONLY,), None, {})
    rej = CandidateEvaluation(_cand("x", "e3"), CandidateStatus.REJECTED, (R.STALE_ODDS,), None, {})
    resp = _recommend([a, review, rej])
    assert resp.outcome is RecommendationOutcome.RECOMMENDED
    assert resp.review_candidates[0].candidate.candidate_id == "r"
    assert resp.rejection_summary == {R.STALE_ODDS: 1}
