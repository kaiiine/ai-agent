"""Intégration COMBO au portefeuille (ADR-ADV-014) : exposition unionnée sur chaque
jambe, bankroll consommé UNE fois, déterminisme (shuffle), non-régression SINGLE,
invariants zéro-stake. Les combos sont alloués APRÈS les singles, budget/exposition
partagés."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.agents.quant.advisor.combos.builder import ComboEvaluation, combo_id
from src.agents.quant.advisor.combos.pricing import price_combo
from src.agents.quant.advisor.combos.sizing import build_combo_candidate, combo_sizing_profile
from src.agents.quant.advisor.domain.candidates import CandidateBet, CandidateEvaluation, CandidateStatus
from src.agents.quant.advisor.domain.enums import DependencyStatus, MaturityPolicy, RiskProfile
from src.agents.quant.advisor.domain.money import ONE
from src.agents.quant.advisor.domain.requests import RecommendationRequest
from src.agents.quant.advisor.portfolio.allocation import allocate_lines
from src.agents.quant.advisor.portfolio.constraints import load_portfolio_caps
from src.agents.quant.advisor.portfolio.exposure import ExposureTracker
from src.agents.quant.advisor.recommendation.simple import load_sizing_profiles

_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
_SIZING = load_sizing_profiles()["BALANCED"]
_COMBO_SIZING = combo_sizing_profile(_SIZING)
_CAPS = load_portfolio_caps()["BALANCED"]


def _cand(cid, event, *, p_low=Decimal("0.60"), odds=Decimal("2.00"), reliability=Decimal("0.75")):
    low, high = p_low, p_low + Decimal("0.05")
    fair = (low + high) / 2
    return CandidateBet(
        candidate_id=cid, event_id=event, sport="football", competition_id="comp:1",
        scheduled_at=_T, bookmaker="winamax", market_id=f"m:{cid}", market_type="MATCH_WINNER",
        selection="home", bookmaker_odds=odds, fair_probability=fair, probability_low=low,
        probability_high=high, fair_odds=Decimal("1.90"), implied_probability=Decimal("0.50"),
        expected_value_mean=fair * odds - ONE, expected_value_low=low * odds - ONE,
        edge_mean=Decimal("0.05"), edge_low=Decimal("0.03"), model_version="m.v1",
        model_maturity="SUPPORTED", calibration_score=reliability, data_quality=Decimal("1.0"),
        freshness_score=Decimal("0.90"), liquidity_score=None, max_stake=None, max_payout=None,
        is_boosted=False, participant_ids=(f"team:{event}:a",),
        exposure_keys=frozenset({f"event:{event}"}), warnings=(), explanation_ref="e",
        source_decision_id=None)


def _eval(cand, reliability=Decimal("0.75")):
    return CandidateEvaluation(cand, CandidateStatus.ELIGIBLE, (), Decimal("1"),
                              {"reliability_component": reliability})


def _combo(a_eval, b_eval, *, margin=Decimal("0.90")):
    pricing = price_combo([a_eval.candidate, b_eval.candidate], margin)
    return ComboEvaluation(
        combo_id=combo_id(a_eval, b_eval), legs=(a_eval, b_eval), compatibility_reason=None,
        dependency_status=DependencyStatus.INDEPENDENT_ENOUGH, pricing=pricing, admissible=True,
        rejection_reason=None, target_odds_match=False,
        min_leg_quality=min(a_eval.candidate.data_quality, b_eval.candidate.data_quality))


def _request(*, bankroll="100", max_selections=5, max_total_stake=None):
    return RecommendationRequest(
        request_id="r", decision_time=_T, bankroll=Decimal(bankroll), currency="EUR",
        allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None,
        allowed_market_types=None, target_total_odds=None,
        max_total_stake=None if max_total_stake is None else Decimal(max_total_stake),
        max_selections=max_selections, max_portfolios=1, allow_singles=True, allow_combos=True,
        max_combo_legs=2, risk_profile=RiskProfile.BALANCED,
        maturity_policy=MaturityPolicy.SUPPORTED_ONLY, ranking_profile="balanced_v1",
        excluded_event_ids=frozenset(), excluded_participant_ids=frozenset(),
        excluded_market_types=frozenset())


# --- §4 Exposition : le stake d'un combo compte sur CHAQUE jambe -----------------
def test_combo_exposure_counts_on_each_leg():
    tracker = ExposureTracker()
    single_a = _cand("a", "A")
    combo_synth = build_combo_candidate(_combo(_eval(_cand("a", "A")), _eval(_cand("b", "B"))))
    bankroll = Decimal("100")
    tracker.allocate(single_a, Decimal("10"))          # event:A += 10
    tracker.allocate(combo_synth, Decimal("5"))         # event:A += 5 ET event:B += 5
    # cap restant sur A = cap - (10+5) : le combo a bien été compté sur A.
    a_cap = _CAPS.max_event_exposure_fraction * bankroll
    assert tracker.remaining_cap(single_a, _CAPS, bankroll) == a_cap - Decimal("15")
    # event:B n'a que le combo (5).
    b_only = _cand("b", "B")
    assert tracker.remaining_cap(b_only, _CAPS, bankroll) == a_cap - Decimal("5")


# --- §4 bankroll consommé UNE fois (pas 2× pour un combo 2 jambes) ---------------
def test_bankroll_consumed_once_not_per_leg():
    a, b = _eval(_cand("a", "A")), _eval(_cand("b", "B"))
    alloc = allocate_lines([a, b], _request(bankroll="100"), sizing=_SIZING, caps=_CAPS,
                           bankroll=Decimal("100"), combos=[_combo(a, b)], combo_sizing=_COMBO_SIZING)
    total = sum((l.stake for l in alloc.lines), Decimal("0")) + \
            sum((c.stake for c in alloc.combo_lines), Decimal("0"))
    assert total <= Decimal("100")                      # jamais 2× le stake combo
    # Budget serré : le combo (alloué après les singles) est borné par le reste.
    tight = allocate_lines([a, b], _request(bankroll="100", max_total_stake="5"), sizing=_SIZING,
                           caps=_CAPS, bankroll=Decimal("100"), combos=[_combo(a, b)],
                           combo_sizing=_COMBO_SIZING)
    tight_total = sum((l.stake for l in tight.lines), Decimal("0")) + \
                  sum((c.stake for c in tight.combo_lines), Decimal("0"))
    assert tight_total <= Decimal("5")                  # budget total partagé singles+combos


# --- §9 déterminisme (shuffle des combos -> même allocation) --------------------
def test_shuffle_combos_same_allocation():
    a, b, c = _eval(_cand("a", "A")), _eval(_cand("b", "B")), _eval(_cand("c", "C"))
    combos = [_combo(a, b), _combo(a, c)]
    req = _request()
    r1 = allocate_lines([a, b, c], req, sizing=_SIZING, caps=_CAPS, bankroll=Decimal("100"),
                        combos=combos, combo_sizing=_COMBO_SIZING)
    r2 = allocate_lines([a, b, c], req, sizing=_SIZING, caps=_CAPS, bankroll=Decimal("100"),
                        combos=list(reversed(combos)), combo_sizing=_COMBO_SIZING)
    # même ENSEMBLE de combos financés + mêmes stakes (indépendant de l'ordre d'entrée).
    assert ({(c.combo.combo_id, c.stake) for c in r1.combo_lines}
            == {(c.combo.combo_id, c.stake) for c in r2.combo_lines})


# --- §18 non-régression SINGLE : les combos n'altèrent jamais les singles -------
def test_singles_identical_with_and_without_combos():
    a, b = _eval(_cand("a", "A")), _eval(_cand("b", "B"))
    req = _request()
    without = allocate_lines([a, b], req, sizing=_SIZING, caps=_CAPS, bankroll=Decimal("100"))
    with_combos = allocate_lines([a, b], req, sizing=_SIZING, caps=_CAPS, bankroll=Decimal("100"),
                                 combos=[_combo(a, b)], combo_sizing=_COMBO_SIZING)
    # Les singles sont alloués AVANT les combos -> stakes SINGLE strictement identiques.
    assert ([(l.evaluation.candidate.candidate_id, l.stake) for l in without.lines]
            == [(l.evaluation.candidate.candidate_id, l.stake) for l in with_combos.lines])


# --- §7 zéro-stake : jamais de ligne COMBO financée à 0 --------------------------
def test_zero_bankroll_no_combo_line():
    a, b = _eval(_cand("a", "A")), _eval(_cand("b", "B"))
    # bankroll=0 passé à l'allocation (la requête exige > 0, l'allocation prend le sien).
    alloc = allocate_lines([a, b], _request(), sizing=_SIZING, caps=_CAPS,
                           bankroll=Decimal("0"), combos=[_combo(a, b)], combo_sizing=_COMBO_SIZING)
    assert alloc.combo_lines == [] and alloc.lines == []


def test_non_positive_kelly_combo_not_materialized():
    # Combo sans edge à la borne basse (proba basse) -> Kelly <= 0 -> aucune ligne.
    a = _eval(_cand("a", "A", p_low=Decimal("0.30"), odds=Decimal("1.50")))
    b = _eval(_cand("b", "B", p_low=Decimal("0.30"), odds=Decimal("1.50")))
    alloc = allocate_lines([], _request(), sizing=_SIZING, caps=_CAPS, bankroll=Decimal("100"),
                           combos=[_combo(a, b)], combo_sizing=_COMBO_SIZING)
    assert alloc.combo_lines == []
    assert alloc.combo_dropped and alloc.combo_dropped[0][1] == "STAKE_NON_POSITIVE"
