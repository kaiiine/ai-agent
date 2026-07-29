"""Portfolio Optimizer multi-single (Lot 8, ADR-ADV-002/007 + current-state §10.5).

Fixtures ELIGIBLE/SUPPORTED. Couvre : budget bankroll/max_total_stake, caps
événement/participant/bookmaker, concentration, granularité (arrondi vers le bas
APRÈS les caps), stake>0 indépendant de min_line_stake, alternatives ancrées
ordonnées/dédupliquées, indépendance à l'ordre d'entrée (shuffle), profils.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from decimal import Decimal

from src.agents.quant.advisor.domain.candidates import CandidateBet, CandidateEvaluation
from src.agents.quant.advisor.domain.enums import CandidateStatus, MaturityPolicy, RiskProfile
from src.agents.quant.advisor.domain.requests import OddsRange, RecommendationRequest
from src.agents.quant.advisor.portfolio import build_portfolios, load_portfolio_caps
from src.agents.quant.advisor.portfolio.constraints import PortfolioCaps
from src.agents.quant.advisor.ranking import load_ranking_profiles, rank
from src.agents.quant.advisor.recommendation import load_sizing_profiles

_KO = datetime(2026, 8, 1, 17, tzinfo=timezone.utc)
_DEC = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
_SIZING = load_sizing_profiles()
_CAPS = load_portfolio_caps()
_RANK = load_ranking_profiles()["balanced_v1"]


def _cand(cid, event="e1", p_low=Decimal("0.90"), odds=Decimal("2.10"), data_quality=Decimal("1.0"),
          max_stake=None, max_payout=None, participants=("pa", "pb"), competition="c1") -> CandidateBet:
    low = p_low
    high = min(low + Decimal("0.05"), Decimal("1.0"))
    fair = (low + high) / 2
    exposure = {f"event:{event}", f"competition:{competition}", "bookmaker:winamax"}
    exposure.update(f"participant:{p}" for p in participants)
    return CandidateBet(
        candidate_id=cid, event_id=event, sport="football", competition_id=competition,
        scheduled_at=_KO, bookmaker="winamax", market_id=f"m:{cid}", market_type="MATCH_WINNER",
        selection="home", bookmaker_odds=odds, fair_probability=fair, probability_low=low,
        probability_high=high, fair_odds=Decimal("1.90"), implied_probability=Decimal("0.4762"),
        expected_value_mean=fair * odds - Decimal("1"), expected_value_low=low * odds - Decimal("1"),
        edge_mean=Decimal("0.05"), edge_low=Decimal("0.03"), model_version="m.v1",
        model_maturity="SUPPORTED", calibration_score=None, data_quality=data_quality,
        freshness_score=Decimal("0.90"), liquidity_score=None, max_stake=max_stake,
        max_payout=max_payout, is_boosted=False, participant_ids=tuple(participants),
        exposure_keys=frozenset(exposure), warnings=(), explanation_ref="expl", source_decision_id=None)


def _elig(cid, event="e1", reliability=Decimal("0.60"), score=Decimal("0.5"), **kw) -> CandidateEvaluation:
    return CandidateEvaluation(_cand(cid, event, **kw), CandidateStatus.ELIGIBLE, (), score,
                               {"reliability_component": reliability})


def _request(bankroll=Decimal("100"), max_total_stake=Decimal("100"), max_selections=20,
             max_portfolios=5, risk=RiskProfile.BALANCED) -> RecommendationRequest:
    return RecommendationRequest(
        request_id="r1", decision_time=_DEC, bankroll=bankroll, currency="EUR",
        allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None,
        allowed_market_types=None, target_total_odds=OddsRange(Decimal("2.00"), Decimal("3.00")),
        max_total_stake=max_total_stake, max_selections=max_selections, max_portfolios=max_portfolios,
        allow_singles=True, allow_combos=False, max_combo_legs=2, risk_profile=risk,
        maturity_policy=MaturityPolicy.SUPPORTED_ONLY, ranking_profile="balanced_v1",
        excluded_event_ids=frozenset(), excluded_participant_ids=frozenset(),
        excluded_market_types=frozenset())


def _build(ranked, request=None, caps=None):
    return build_portfolios(ranked, request or _request(),
                            sizing_profiles=_SIZING, caps_config=caps or _CAPS)


def _ids(pf):
    return tuple(l.legs[0].candidate_id for l in pf.lines)


# ── Budget bankroll / max_total_stake ─────────────────────────────────────────
def test_total_stake_within_budget():
    ranked = [_elig("c1", "e1", competition="k1"), _elig("c2", "e2", competition="k2"),
              _elig("c3", "e3", competition="k3")]
    pf = _build(ranked, _request(bankroll=Decimal("100"), max_total_stake=Decimal("15")))[0]
    assert pf.total_stake <= Decimal("15")                    # budget = min(bankroll, max_total_stake)
    assert pf.total_stake == sum((l.stake for l in pf.lines), Decimal("0"))


def test_bankroll_not_fully_used():
    pf = _build([_elig("c1", "e1")], _request(bankroll=Decimal("100")))[0]
    assert pf.total_stake < Decimal("100")
    assert pf.unallocated_bankroll == Decimal("100") - pf.total_stake and pf.unallocated_bankroll > 0


# ── Caps d'exposition / concentration ─────────────────────────────────────────
def test_event_cap_limits_concentration():
    # 3 sélections du MÊME événement : le cap événement (0.20×100=20) borne l'exposition.
    ranked = [_elig("c1", "e1"), _elig("c2", "e1"), _elig("c3", "e1")]
    pf = _build(ranked)[0]
    assert sum((l.stake for l in pf.lines), Decimal("0")) <= Decimal("20")
    assert len(pf.lines) == 2                                 # 2×10 = cap, 3e écartée
    assert pf.concentration_score == Decimal("1")             # tout sur un seul événement


def test_bookmaker_cap_binds():
    # 10 événements distincts, même bookmaker : cap bookmaker (0.70×100=70) borne le total.
    ranked = [_elig(f"c{i}", f"e{i}", competition=f"k{i}", participants=(f"pa{i}", f"pb{i}"))
              for i in range(10)]
    pf = _build(ranked)[0]
    assert sum((l.stake for l in pf.lines), Decimal("0")) == Decimal("70")   # 7×10, 8e écartée


# ── Granularité (arrondi vers le bas APRÈS les caps) ──────────────────────────
def test_granularity_rounds_down():
    pf = _build([_elig("c1", "e1", max_payout=Decimal("3.0"))])[0]  # max_payout/odds = 1.428...
    stake = pf.lines[0].stake
    assert stake == Decimal("1.42")                           # arrondi vers le bas au pas 0.01
    assert stake * Decimal("2.10") <= Decimal("3.0")          # cap payout respecté APRÈS arrondi


def test_rounding_never_exceeds_any_cap():
    pf = _build([_elig("c1", "e1", max_stake=Decimal("1.457"))])[0]
    stake = pf.lines[0].stake
    assert stake == Decimal("1.45") and stake <= Decimal("1.457")


def test_stake_rounds_to_zero_no_line():
    # max_stake < granularité -> arrondi 0 -> aucune ligne -> aucun portefeuille.
    assert _build([_elig("c1", "e1", max_stake=Decimal("0.005"))]) == ()


def test_stake_below_min_dropped_with_reason():
    ranked = [_elig("c1", "e1", competition="k1"),
              _elig("c2", "e2", competition="k2", max_stake=Decimal("0.15"))]  # < min_line_stake 0.20
    pf = _build(ranked)[0]
    assert _ids(pf) == ("c1",)                                # c2 écartée
    assert any("c2" in r and "STAKE_BELOW_MIN" in r for r in pf.explanation.rejected_alternatives)


def test_min_stake_zero_still_forbids_zero_stake():
    caps0 = {"BALANCED": PortfolioCaps(
        Decimal("0.20"), Decimal("0.20"), Decimal("0.40"), Decimal("0.70"),
        stake_granularity=Decimal("0.01"), min_line_stake=Decimal("0"))}
    # 0.005 -> arrondi 0 -> interdit même avec min_line_stake=0 (invariant stake>0 indépendant).
    assert _build([_elig("c1", "e1", max_stake=Decimal("0.005"))], caps=caps0) == ()


# ── Alternatives ancrées : ordre + déduplication ──────────────────────────────
def test_alternatives_anchored_ordered_and_deduped():
    # Même événement, cap -> 2 lignes ; l'ancrage explore d'autres paires.
    ranked = [_elig("c1", "e1"), _elig("c2", "e1"), _elig("c3", "e1")]
    pfs = _build(ranked)
    assert _ids(pfs[0]) == ("c1", "c2")                       # primaire : glouton canonique
    assert _ids(pfs[1]) == ("c3", "c1")                       # alternative ancrée sur c3 (rang 2)
    assert len(pfs) == 2                                       # c2-ancré == primaire -> dédupliqué


def test_max_portfolios_caps_alternatives():
    ranked = [_elig("c1", "e1"), _elig("c2", "e1"), _elig("c3", "e1")]
    assert len(_build(ranked, _request(max_portfolios=1))) == 1


# ── Déterminisme / ordre d'entrée ─────────────────────────────────────────────
def test_deterministic_same_stakes():
    ranked = [_elig("c1", "e1", competition="k1"), _elig("c2", "e2", competition="k2")]
    assert _build(ranked) == _build(ranked)


def test_input_order_independence_through_ranking():
    # shuffle(candidats) -> rank (ordre-indépendant) -> optimize -> mêmes portefeuilles.
    evals = [CandidateEvaluation(_cand(f"c{i}", f"e{i}", p_low=Decimal("0.50") + Decimal(i) / 100,
                                       competition=f"k{i}"), CandidateStatus.ELIGIBLE, (), None, {})
             for i in range(5)]

    def run(evs):
        return _build(list(rank(evs, profile=_RANK).ranked), _request())

    base = run(evals)
    base_sig = [( _ids(pf), tuple(l.stake for l in pf.lines)) for pf in base]
    for _ in range(6):
        shuffled = evals[:]
        random.shuffle(shuffled)
        assert [(_ids(pf), tuple(l.stake for l in pf.lines)) for pf in run(shuffled)] == base_sig


# ── Profils ───────────────────────────────────────────────────────────────────
def test_conservative_allocates_less_than_balanced():
    cand = _elig("c1", "e1")
    cons = _build([cand], _request(risk=RiskProfile.CONSERVATIVE))[0]
    bal = _build([cand], _request(risk=RiskProfile.BALANCED))[0]
    assert cons.total_stake < bal.total_stake                 # fractional_kelly + caps plus serrés


def test_target_odds_match_only_for_single_line():
    single = _build([_elig("c1", "e1")], _request())[0]
    assert single.target_odds_match is True                   # 1 ligne, cote 2.10 ∈ [2,3]
    multi = _build([_elig("c1", "e1", competition="k1"), _elig("c2", "e2", competition="k2")])[0]
    assert multi.target_odds_match is False                   # multi-single : pas de cote totale
