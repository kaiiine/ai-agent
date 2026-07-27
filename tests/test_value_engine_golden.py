"""Golden no-vig / EV : le value_engine reproduit EXACTEMENT le noyau gelé
`quant/ev_engine.py` (importé, jamais copié). Valeurs littérales FIGÉES depuis
l'implémentation actuelle ; tolérance 1e-9. En complément des 17 tests gelés."""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness,
    MarketPrediction,
    PredictionExplanation,
    UncertaintyStatus,
)
from src.agents.quant.betting_engine.core.odds import OddsSnapshot
from src.agents.quant.betting_engine.value_engine import evaluate_selection
from src.agents.quant.betting_engine.value_engine import margin_removal
from src.agents.quant.betting_engine.value_engine.expected_value import ev, minimum_odds_for_value

TOL = 1e-9
_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _odds(sel, o):
    return OddsSnapshot("ev1", "MATCH_WINNER", sel, o, _T, "winamax")


def _market():
    return [_odds("home", 2.15), _odds("draw", 3.40), _odds("away", 3.20)]


def _pred(sel, p):
    return MarketPrediction(
        "football", "MATCH_WINNER", sel, p, p, p, UncertaintyStatus.NOT_ESTIMATED,
        "m.v0", 1.0, DataReadiness.EXPERIMENTAL, _T, PredictionExplanation([], set(), [], []),
    )


# ── Noyau (kernel) : valeurs figées ───────────────────────────────────────────
def test_no_vig_frozen_and_sums_to_one():
    nv = margin_removal.no_vig(_market())
    assert abs(nv["home"] - 0.4340) < TOL
    assert abs(nv["draw"] - 0.2744) < TOL
    assert abs(nv["away"] - 0.2916) < TOL
    assert abs(sum(nv.values()) - 1.0) < TOL


def test_ev_and_minimum_odds_frozen():
    assert abs(ev(0.55, 2.15) - 0.1825) < TOL
    assert abs(ev(0.28, 3.40) - (-0.048)) < TOL
    assert abs(minimum_odds_for_value(0.55) - 1.927) < TOL


def test_implied_raw_frozen():
    assert abs(margin_removal.implied_raw(2.15) - (1 / 2.15)) < TOL


# ── Via evaluate_selection : mêmes valeurs propagées dans BettingDecision ──────
def test_betting_decision_metrics_match_frozen_reference():
    d = evaluate_selection(_pred("home", 0.55), _market())
    assert abs(d.implied_probability_raw - 0.4651) < TOL
    assert abs(d.no_vig_probability - 0.4340) < TOL
    assert abs(d.expected_value - 0.1825) < TOL
    assert abs(d.edge - (0.55 - 0.4340)) < TOL
