"""Contrat value_engine (§8) : évaluation par sélection, cap BE-FR-011, refus
boosté, cohérence marché. Hermétique (OddsSnapshot + MarketPrediction construits)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.core.errors import MarketCoherenceError
from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness,
    MarketPrediction,
    PredictionExplanation,
    UncertaintyStatus,
)
from src.agents.quant.betting_engine.core.odds import OddsSnapshot
from src.agents.quant.betting_engine.value_engine import EvaluationStatus, evaluate_selection

_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _odds(sel, o, *, boost=False, event_id="ev1", bookmaker="winamax", when=_T,
          market_type="MATCH_WINNER"):
    return OddsSnapshot(event_id, market_type, sel, o, when, bookmaker, is_boosted=boost)


def _market(**home_kw):
    return [_odds("home", 2.15, **home_kw), _odds("draw", 3.40), _odds("away", 3.20)]


def _pred(sel, p, *, status=DataReadiness.EXPERIMENTAL,
          uncertainty=UncertaintyStatus.NOT_ESTIMATED):
    return MarketPrediction(
        "football", "MATCH_WINNER", sel, p, p, p, uncertainty, "m.v0", 1.0, status, _T,
        PredictionExplanation([], set(), [], []),
    )


# ── EV calculé pour audit, mais décision plafonnée ────────────────────────────
def test_experimental_computes_metrics_but_abstains():
    d = evaluate_selection(_pred("home", 0.55), _market())
    assert d.evaluation_status == EvaluationStatus.EVALUATED
    assert d.expected_value is not None and d.no_vig_probability is not None
    assert d.decision == "ABSTAIN"
    assert "MODEL_NOT_SUPPORTED" in d.reasons


# ── BE-FR-011 STRICT : EV énorme + EXPERIMENTAL -> jamais BET ──────────────────
def test_huge_ev_on_experimental_model_never_bets():
    market = [_odds("home", 2.5), _odds("draw", 3.4), _odds("away", 3.0)]  # cohérent (overround>1)
    d = evaluate_selection(_pred("home", 0.95), market)                    # EV brut ~1.4
    assert d.expected_value > 1.0                                          # EV énorme calculé
    assert d.decision == "ABSTAIN"
    assert d.decision != "BET"
    assert "MODEL_NOT_SUPPORTED" in d.reasons


def test_nothing_bypasses_the_cap_even_perfect_inputs():
    market = [_odds("home", 2.5), _odds("draw", 3.4), _odds("away", 3.0)]   # cohérent
    d = evaluate_selection(_pred("home", 0.90, uncertainty=UncertaintyStatus.NOT_ESTIMATED), market)
    assert d.decision == "ABSTAIN" and "MODEL_NOT_SUPPORTED" in d.reasons


# ── Offre boostée : refus explicite, jamais évaluée comme standard ────────────
def test_boosted_offer_is_refused_never_evaluated():
    d = evaluate_selection(_pred("home", 0.55), _market(boost=True))
    assert d.decision == "ABSTAIN"
    assert d.reasons == ["UNSUPPORTED_ODDS_TYPE"]
    assert d.evaluation_status == EvaluationStatus.NOT_EVALUATED
    # métriques NON calculées -> None, jamais 0
    assert d.expected_value is None
    assert d.no_vig_probability is None
    assert d.implied_probability_raw is None
    assert d.edge is None


def test_boosted_never_bets_even_with_huge_edge():
    market = [_odds("home", 6.0, boost=True), _odds("draw", 3.5), _odds("away", 2.5)]
    d = evaluate_selection(_pred("home", 0.95), market)
    assert d.decision != "BET"
    assert d.reasons == ["UNSUPPORTED_ODDS_TYPE"]


# ── Incertitude non estimée, distincte du cap ─────────────────────────────────
def test_uncertainty_not_estimated_is_flagged_separately_from_cap():
    d = evaluate_selection(_pred("home", 0.55), _market())
    assert "UNCERTAINTY_NOT_ESTIMATED" in d.reasons
    assert "MODEL_NOT_SUPPORTED" in d.reasons
    assert d.reasons.index("MODEL_NOT_SUPPORTED") != d.reasons.index("UNCERTAINTY_NOT_ESTIMATED")


def test_probability_interval_not_used_for_conservative_ev():
    # EV calculé sur le point (fair_probability), pas sur low/high.
    d = evaluate_selection(_pred("home", 0.55), _market())
    assert d.expected_value == round(0.55 * 2.15 - 1, 4)
    # aucun champ d'EV prudent/optimiste dérivé de l'intervalle
    assert not {"conservative_ev", "optimistic_ev"} & set(vars(d))


# ── Cohérence du marché ───────────────────────────────────────────────────────
@pytest.mark.parametrize("market,pred", [
    ([_odds("home", 2.1), _odds("draw", 3.4)], _pred("home", 0.5)),                     # incomplet
    ([_odds("home", 2.1), _odds("home", 2.2), _odds("away", 3.2)], _pred("home", 0.5)),  # dupliqué
    ([_odds("home", 1.0), _odds("draw", 3.4), _odds("away", 3.2)], _pred("home", 0.5)),  # cote ≤ 1
    ([_odds("home", 2.1), _odds("draw", 3.4), _odds("away", 3.2)], _pred("over", 0.5)),  # sel absente
    ([_odds("home", 2.1), _odds("draw", 3.4, bookmaker="betclic"), _odds("away", 3.2)],  # bookmakers ≠
     _pred("home", 0.5)),
    ([_odds("home", 2.1), _odds("draw", 3.4, event_id="ev2"), _odds("away", 3.2)],       # événements ≠
     _pred("home", 0.5)),
    ([_odds("home", 2.1), _odds("draw", 3.4, when=_T + timedelta(minutes=5)),            # temporel
      _odds("away", 3.2)], _pred("home", 0.5)),
])
def test_incoherent_markets_raise(market, pred):
    with pytest.raises(MarketCoherenceError):
        evaluate_selection(pred, market)


def test_prediction_market_type_mismatch_raises():
    market = [_odds("home", 2.1, market_type="OVER_UNDER"), _odds("draw", 3.4, market_type="OVER_UNDER"),
              _odds("away", 3.2, market_type="OVER_UNDER")]
    with pytest.raises(MarketCoherenceError):
        evaluate_selection(_pred("home", 0.5), market)   # prediction.market_type=MATCH_WINNER


def test_overround_checked_separately_from_completeness():
    # Structurellement complet {home,draw,away} MAIS overround ≤ 1 -> refus quand même.
    market = [_odds("home", 5.0), _odds("draw", 5.0), _odds("away", 5.0)]   # Σ implicites = 0.6
    with pytest.raises(MarketCoherenceError):
        evaluate_selection(_pred("home", 0.5), market)


def test_completeness_requires_exact_selection_set():
    market = [_odds("home", 2.1), _odds("draw", 3.4), _odds("over", 3.2)]   # 'over' ∉ {home,draw,away}
    with pytest.raises(MarketCoherenceError):
        evaluate_selection(_pred("home", 0.5), market)
