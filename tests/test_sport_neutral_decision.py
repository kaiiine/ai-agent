"""Preuve d'architecture MULTISPORT au niveau de la frontière de décision (§7).

La frontière `evaluate_selection` (Betting Engine) est neutre au sport : elle décide
depuis un contrat économique générique (proba modèle + cotes), sans hypothèse football.

Démontré :
- un marché 2-way (basket-like), market_type hors 1X2, traverse la frontière ;
- un module SUPPORTED synthétique atteint réellement le chemin BET, SANS bypass ;
- le cap EXPERIMENTAL (BE-FR-011) tient quel que soit le sport (jamais BET) ;
- l'étiquette `sport` n'influence PAS la décision ;
- un sport sans module enregistré est MODEL_UNAVAILABLE (abstention propre).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.betting_engine.capability import market_capability
from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness,
    MarketPrediction,
    PredictionExplanation,
    UncertaintyStatus,
)
from src.agents.quant.betting_engine.core.odds import OddsSnapshot
from src.agents.quant.betting_engine.value_engine import evaluate_selection

_T = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
_MARKET = "SYNTH_MONEYLINE"          # 2-way, hors _EXPECTED_SELECTIONS (donc pas 3-way-verrouillé)


def _pred(sport, selection, calibration, *, low=0.60, fair=0.62, high=0.64, dq=0.95,
          uncertainty=UncertaintyStatus.ESTIMATED) -> MarketPrediction:
    return MarketPrediction(
        sport=sport, market_type=_MARKET, selection=selection,
        fair_probability=fair, probability_low=low, probability_high=high,
        uncertainty_status=uncertainty, model_version="synth.v0", data_quality=dq,
        calibration_status=calibration, point_in_time=_T,
        explanation=PredictionExplanation([], set(), [], []))


def _two_way_market(event_id="evt:synth", home_odds=1.90, away_odds=2.10) -> list[OddsSnapshot]:
    return [
        OddsSnapshot(event_id, _MARKET, "home", home_odds, _T, "winamax"),
        OddsSnapshot(event_id, _MARKET, "away", away_odds, _T, "winamax"),   # 2 issues, pas 3
    ]


def test_two_way_supported_reaches_bet_without_bypass():
    # Un modèle SUPPORTED synthétique atteint BET via la frontière normale (aucun bypass) —
    # et sur un marché 2-WAY, prouvant que la frontière n'est pas verrouillée au 1X2 football.
    d = evaluate_selection(_pred("basketball", "home", DataReadiness.SUPPORTED), _two_way_market())
    assert d.decision == "BET"
    assert d.worst_case_ev is not None and d.worst_case_ev >= 0.02   # borne basse réelle
    assert d.model_reliability == 0.75                               # reliability policy explicite


def test_experimental_never_bets_any_sport():
    # Cap BE-FR-011 : EXPERIMENTAL -> ABSTAIN, quel que soit le sport, même EV énorme.
    for sport in ("football", "basketball", "tennis"):
        d = evaluate_selection(
            _pred(sport, "home", DataReadiness.EXPERIMENTAL, low=0.90, fair=0.92, high=0.94),
            _two_way_market(home_odds=3.0, away_odds=1.45))    # overround > 1 (marge présente)
        assert d.decision == "ABSTAIN"
        assert "MODEL_NOT_SUPPORTED" in d.reasons


def test_sport_label_does_not_change_decision():
    # Même contrat économique -> même décision, que l'étiquette soit basket ou tennis.
    dq_basket = evaluate_selection(_pred("basketball", "home", DataReadiness.SUPPORTED), _two_way_market())
    dq_tennis = evaluate_selection(_pred("tennis", "home", DataReadiness.SUPPORTED), _two_way_market())
    assert (dq_basket.decision, dq_basket.expected_value, dq_basket.worst_case_ev) == \
           (dq_tennis.decision, dq_tennis.expected_value, dq_tennis.worst_case_ev)


def test_unregistered_sport_is_model_unavailable():
    # Aucun module live enregistré pour basket/tennis -> capability MODEL_UNAVAILABLE.
    assert market_capability("basketball", "MONEYLINE") == (False, "UNAVAILABLE")
    assert market_capability("tennis", "MATCH_WINNER") == (False, "UNAVAILABLE")


def test_selection_order_does_not_change_decision():
    # L'ordre des issues dans le marché n'affecte pas la décision (ensembles, pas listes).
    market = _two_way_market()
    d1 = evaluate_selection(_pred("basketball", "home", DataReadiness.SUPPORTED), market)
    d2 = evaluate_selection(_pred("basketball", "home", DataReadiness.SUPPORTED), list(reversed(market)))
    assert d1.decision == d2.decision == "BET"
    assert d1.expected_value == d2.expected_value
