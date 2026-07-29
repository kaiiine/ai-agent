"""Combo Builder (Lot 9). Compatibilité vs dépendance strictement séparées ;
refus strict UNKNOWN ; pricing mean/low prudent ; identité structurelle stable ;
ranking déterministe ; intégration jusqu'à la frontière du fork sizing COMBO.
"""

from __future__ import annotations

import ast
import json
import pathlib
import random
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.advisor.combos import build_combos, combo_id, load_combo_policy
from src.agents.quant.advisor.combos import builder as _builder
from src.agents.quant.advisor.combos.builder import ComboSizingRequired, evaluate_pair, to_portfolio_line
from src.agents.quant.advisor.combos.compatibility import (
    DIFFERENT_BOOKMAKERS, DUPLICATE_LEG, FORBIDDEN_MARKET, NON_ELIGIBLE_LEG, check_compatibility,
)
from src.agents.quant.advisor.combos.dependency import classify
from src.agents.quant.advisor.combos.policy import ComboPolicy
from src.agents.quant.advisor.combos.pricing import price_combo
from src.agents.quant.advisor.domain.candidates import CandidateBet, CandidateEvaluation
from src.agents.quant.advisor.domain.enums import (
    CandidateStatus, DependencyStatus, MaturityPolicy, RiskProfile,
)
from src.agents.quant.advisor.domain.requests import OddsRange, RecommendationRequest
from src.agents.quant.advisor.policy import reason_codes as R

_KO = datetime(2026, 8, 1, 17, tzinfo=timezone.utc)
_DEC = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)


def _cand(cid, event="e1", market_id="m1", selection="home", bookmaker="winamax",
          p_low=Decimal("0.60"), fair=Decimal("0.65"), odds=Decimal("2.00"),
          data_quality=Decimal("1.0"), participants=("pa", "pb"), market_type="MATCH_WINNER"):
    return CandidateBet(
        candidate_id=cid, event_id=event, sport="football", competition_id="comp:1",
        scheduled_at=_KO, bookmaker=bookmaker, market_id=market_id, market_type=market_type,
        selection=selection, bookmaker_odds=odds, fair_probability=fair, probability_low=p_low,
        probability_high=fair, fair_odds=Decimal("1.50"), implied_probability=Decimal("0.50"),
        expected_value_mean=Decimal("0.10"), expected_value_low=Decimal("0.05"),
        edge_mean=Decimal("0.05"), edge_low=Decimal("0.02"), model_version="m.v1",
        model_maturity="SUPPORTED", calibration_score=None, data_quality=data_quality,
        freshness_score=Decimal("0.9"), liquidity_score=None, max_stake=None, max_payout=None,
        is_boosted=False, participant_ids=tuple(participants),
        exposure_keys=frozenset({f"event:{event}"}), warnings=(), explanation_ref="e",
        source_decision_id=None)


def _elig(cid, status=CandidateStatus.ELIGIBLE, **kw):
    return CandidateEvaluation(_cand(cid, **kw), status, (), Decimal("0.5"),
                               {"reliability_component": Decimal("0.6")})


def _request(allow_combos=True, target=OddsRange(Decimal("2.00"), Decimal("6.00"))):
    return RecommendationRequest(
        request_id="r1", decision_time=_DEC, bankroll=Decimal("100"), currency="EUR",
        allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None,
        allowed_market_types=None, target_total_odds=target, max_total_stake=Decimal("100"),
        max_selections=5, max_portfolios=3, allow_singles=True, allow_combos=allow_combos,
        max_combo_legs=2, risk_profile=RiskProfile.BALANCED,
        maturity_policy=MaturityPolicy.SUPPORTED_ONLY, ranking_profile="balanced_v1",
        excluded_event_ids=frozenset(), excluded_participant_ids=frozenset(),
        excluded_market_types=frozenset())


def _policy(safety_margin=Decimal("0.90"), min_combo_ev=Decimal("0.02"), top_k=8):
    return ComboPolicy("1", "2026-07-29", "x", top_k, 2, safety_margin, min_combo_ev)


# ── Compatibilité (avant dépendance) ──────────────────────────────────────────
def test_different_bookmakers_never_unknown():
    r = check_compatibility(_elig("a"), _elig("b", event="e2", participants=("pc", "pd"),
                                              bookmaker="betclic"), _request())
    assert r == DIFFERENT_BOOKMAKERS


def test_non_eligible_leg():
    review = _elig("b", status=CandidateStatus.REVIEW_ONLY, event="e2", participants=("pc", "pd"))
    assert check_compatibility(_elig("a"), review, _request()) == NON_ELIGIBLE_LEG


def test_forbidden_market():
    req = replace(_request(), allowed_market_types=frozenset({"OVER_UNDER"}))
    assert check_compatibility(_elig("a"), _elig("b", event="e2", participants=("pc", "pd")), req) == FORBIDDEN_MARKET


def test_duplicate_leg_distinct_from_incompatible():
    assert check_compatibility(_elig("a"), _elig("a"), _request()) == DUPLICATE_LEG


# ── Dépendance ────────────────────────────────────────────────────────────────
def test_same_event_other_market_structurally_dependent():
    a = _cand("a", event="e1", market_id="m1", selection="home")
    b = _cand("b", event="e1", market_id="m2", selection="over")
    assert classify(a, b) is DependencyStatus.STRUCTURALLY_DEPENDENT


def test_incompatible_priority_over_structural():
    # Même événement + même marché + sélections différentes = INCOMPATIBLE (pas STRUCTURALLY).
    a = _cand("a", event="e1", market_id="m1", selection="home")
    b = _cand("b", event="e1", market_id="m1", selection="away")
    assert classify(a, b) is DependencyStatus.INCOMPATIBLE


def test_shared_participant_statistically_dependent():
    a = _cand("a", event="e1", participants=("shared", "x"))
    b = _cand("b", event="e2", participants=("shared", "y"))
    assert classify(a, b) is DependencyStatus.STATISTICALLY_DEPENDENT


def test_unknown_when_participants_not_verifiable():
    a = _cand("a", event="e1", participants=())
    b = _cand("b", event="e2", participants=("y", "z"))
    assert classify(a, b) is DependencyStatus.UNKNOWN


def test_independent_enough_distinct_events_disjoint_participants():
    a = _cand("a", event="e1", participants=("a1", "a2"))
    b = _cand("b", event="e2", participants=("b1", "b2"))
    assert classify(a, b) is DependencyStatus.INDEPENDENT_ENOUGH


def test_classify_symmetric():
    a = _cand("a", event="e1", participants=("a1", "a2"))
    b = _cand("b", event="e2", participants=("b1", "b2"))
    assert classify(a, b) == classify(b, a)


# ── Identité stable + symétrie ────────────────────────────────────────────────
def _indep_pair():
    return _elig("a", event="e1", participants=("a1", "a2")), _elig("b", event="e2", participants=("b1", "b2"))


def test_combo_id_order_independent():
    a, b = _indep_pair()
    assert combo_id(a, b) == combo_id(b, a)


def test_build_symmetry_same_id_pricing_order():
    a, b = _indep_pair()
    c1, _ = evaluate_pair(a, b, _request(), _policy())
    c2, _ = evaluate_pair(b, a, _request(), _policy())
    assert c1.combo_id == c2.combo_id
    assert c1.pricing == c2.pricing
    assert [l.candidate.candidate_id for l in c1.legs] == [l.candidate.candidate_id for l in c2.legs]


def test_same_id_across_configs_but_different_pricing():
    a, b = _indep_pair()
    c_lo, _ = evaluate_pair(a, b, _request(), _policy(safety_margin=Decimal("0.80")))
    c_hi, _ = evaluate_pair(a, b, _request(), _policy(safety_margin=Decimal("0.95")))
    assert c_lo.combo_id == c_hi.combo_id                     # identité indépendante de la config
    assert c_lo.pricing.combined_prob_mean != c_hi.pricing.combined_prob_mean


def test_same_id_admission_differs_with_min_combo_ev():
    a, b = _indep_pair()
    lax, _ = evaluate_pair(a, b, _request(), _policy(min_combo_ev=Decimal("0.02")))
    strict, _ = evaluate_pair(a, b, _request(), _policy(min_combo_ev=Decimal("5.0")))
    assert lax.combo_id == strict.combo_id
    assert lax.admissible and not strict.admissible


# ── Pricing ───────────────────────────────────────────────────────────────────
def test_pricing_margin_and_invariants():
    legs = [_cand("a", odds=Decimal("2.00")), _cand("b", odds=Decimal("2.00"))]
    p = price_combo(legs, Decimal("0.90"))
    assert p.combined_odds == Decimal("4.00")                 # produit exact
    assert p.combined_prob_mean == Decimal("0.65") * Decimal("0.65") * Decimal("0.90")
    assert p.combined_prob_low == Decimal("0.60") * Decimal("0.60") * Decimal("0.90")
    assert Decimal("0") <= p.combined_prob_low <= p.combined_prob_mean <= Decimal("1")
    assert p.expected_value >= p.worst_case_ev
    assert p.expected_value != p.worst_case_ev                # probability_low != fair_probability


def test_admission_on_worst_case_not_mean():
    # EV moyenne positive mais worst_case_ev sous le seuil -> rejeté.
    a = _elig("a", event="e1", p_low=Decimal("0.52"), fair=Decimal("0.65"), participants=("a1", "a2"))
    b = _elig("b", event="e2", p_low=Decimal("0.52"), fair=Decimal("0.65"), participants=("b1", "b2"))
    combo, _ = evaluate_pair(a, b, _request(), _policy(min_combo_ev=Decimal("0.02")))
    assert combo.pricing.expected_value > 0
    assert combo.pricing.worst_case_ev < Decimal("0.02")
    assert not combo.admissible and combo.rejection_reason == "LOW_WORST_CASE_EV"


# ── Validation de configuration ───────────────────────────────────────────────
def test_config_validation():
    with pytest.raises(ValueError):
        _policy(safety_margin=Decimal("0"))
    with pytest.raises(ValueError):
        _policy(safety_margin=Decimal("1.0"))
    with pytest.raises(ValueError):
        _policy(top_k=0)
    with pytest.raises(ValueError):
        ComboPolicy("1", "2026", "x", 8, 3, Decimal("0.9"), Decimal("0.02"))   # max_combo_legs != 2


def test_loader_rejects_bad_checksum(tmp_path):
    good = json.loads((pathlib.Path("configs/advisor/combo_policy.json")).read_text())
    good["checksum"] = "deadbeef"
    p = tmp_path / "combo.json"
    p.write_text(json.dumps(good))
    with pytest.raises(ValueError):
        load_combo_policy(p)


def test_loader_rejects_missing_min_combo_ev(tmp_path):
    good = json.loads((pathlib.Path("configs/advisor/combo_policy.json")).read_text())
    del good["min_combo_ev"]
    p = tmp_path / "combo.json"
    p.write_text(json.dumps(good))
    with pytest.raises(ValueError):
        load_combo_policy(p)


# ── Ranking / déterminisme ────────────────────────────────────────────────────
def _ranked_indep(n):
    # n candidats, événements/participants disjoints -> toutes les paires INDEPENDENT_ENOUGH.
    return [_elig(f"c{i}", event=f"e{i}", participants=(f"p{i}a", f"p{i}b"),
                  odds=Decimal("2.00") + Decimal(i) / 10) for i in range(n)]


def test_ranking_by_worst_case_then_ev_then_lexical():
    combos = build_combos(_ranked_indep(4), _request(), _policy())[0].admissible
    wc = [c.pricing.worst_case_ev for c in combos]
    assert wc == sorted(wc, reverse=True)                     # worst_case_ev décroissant


def test_ranking_input_order_independent():
    base = _ranked_indep(5)

    def sig(evs):
        res = build_combos(evs, _request(), _policy())[0]
        return [(c.combo_id, c.pricing.worst_case_ev, c.pricing.expected_value) for c in res.admissible]

    ref = sig(base)
    for _ in range(6):
        shuffled = base[:]
        random.shuffle(shuffled)
        assert sig(shuffled) == ref                           # mêmes combos, ids, métriques, ordre


# ── Frontière : fork sizing COMBO ─────────────────────────────────────────────
def test_to_portfolio_line_raises_sizing_fork():
    combo = build_combos(_ranked_indep(2), _request(), _policy())[0].admissible[0]
    with pytest.raises(ComboSizingRequired):
        to_portfolio_line(combo)                              # jamais de mise improvisée


# ── Intégration jusqu'à la frontière (sans ligne COMBO inventée) ──────────────
def _adapted(cid, event, participants, odds="2.50"):
    from src.agents.quant.advisor.input_adapter.schema import AdaptedEvaluation, AdaptedExplanation
    return AdaptedEvaluation(
        schema_version="1", event_id=event, sport="football", competition_id="comp:1",
        scheduled_at=_KO, participant_ids=participants, observed_at=_DEC, bookmaker="winamax",
        market_id=f"winamax:{event}:MATCH_WINNER", market_type="MATCH_WINNER", selection="home",
        bookmaker_odds=Decimal(odds), fair_probability=Decimal("0.65"), probability_low=Decimal("0.60"),
        probability_high=Decimal("0.65"), uncertainty_status="ESTIMATED", model_version="m.v1",
        model_maturity="SUPPORTED", data_quality=Decimal("1.0"), calibration_score=None,
        freshness_score=Decimal("0.90"), liquidity_score=None, implied_probability_raw=Decimal("0.40"),
        no_vig_probability=Decimal("0.42"), edge=Decimal("0.20"), expected_value=Decimal("0.5"),
        is_boosted=False, decision="ABSTAIN", decision_reasons=("MODEL_NOT_SUPPORTED",), warnings=(),
        explanation=AdaptedExplanation((("f", 1.0),), frozenset(), ("d",), ()), source_decision_id=None)


def _configs():
    from src.agents.quant.advisor.policy import load_policy_config
    from src.agents.quant.advisor.ranking import load_ranking_profiles
    from src.agents.quant.advisor.recommendation import load_sizing_profiles
    from src.agents.quant.advisor.portfolio import load_portfolio_caps
    return dict(policy_config=load_policy_config(), ranking_profiles=load_ranking_profiles(),
                sizing_profiles=load_sizing_profiles(), portfolio_caps=load_portfolio_caps(),
                combo_policy=load_combo_policy())


def test_integration_up_to_sizing_fork():
    from src.agents.quant.advisor.input_adapter.schema import AdaptedBatch
    from src.agents.quant.advisor.pipeline import run_pipeline
    batch = AdaptedBatch("1", _DEC, (_adapted("c1", "e1", ("a1", "a2")),
                                     _adapted("c2", "e2", ("b1", "b2"))), ())
    cfg = _configs()

    off = run_pipeline(batch, _request(allow_combos=False), **cfg)   # builder non appelé
    assert not any(w.startswith(R.COMBO_SIZING_NOT_AVAILABLE) for w in off.warnings)

    on = run_pipeline(batch, _request(allow_combos=True), **cfg)     # builder appelé
    # code STABLE machine-readable, distinguable d'un vrai NO_OPPORTUNITY.
    assert any(w.startswith(R.COMBO_SIZING_NOT_AVAILABLE) for w in on.warnings)
    # aucune PortfolioLine COMBO inventée : la frontière est bloquée par le sizing.
    for pf in on.portfolios:
        for line in pf.lines:
            assert line.line_type.value == "SINGLE"


# ── Pureté / frontières ───────────────────────────────────────────────────────
def test_combos_import_no_engine_or_sport_or_framework():
    root = pathlib.Path("src/agents/quant/advisor/combos")
    forbidden = ("betting_engine", "sports", "langgraph", "langchain", "click", "fastapi",
                 "winamax", "gateway")
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for m in mods:
                assert not any(f in m for f in forbidden), f"{path.name} importe {m}"
