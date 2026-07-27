"""Contrat MarketModel one_x_two (§7) — en complément des golden math."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.core.canonical_event import (
    CanonicalEvent,
    CanonicalMarket,
    CanonicalParticipant,
)
from src.agents.quant.betting_engine.core.errors import (
    InsufficientDataError,
    PointInTimeViolationError,
)
from src.agents.quant.betting_engine.core.feature_set import EventFeatureSet
from src.agents.quant.betting_engine.core.market_model import DataReadiness, MarketModel, UncertaintyStatus
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel
from src.agents.quant.betting_engine.sports.football import manifest

_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
_H = "team:football:fra:psg"
_A = "team:football:fra:marseille"
_HOME = CanonicalMarket("MATCH_WINNER", "home")


def _event():
    return CanonicalEvent(
        "e", "football", "competition:football:fra:ligue1",
        (CanonicalParticipant(_H, "home"), CanonicalParticipant(_A, "away")), _T,
    )


def _features(*, home=None, away=None, missing=None, as_of=_T):
    """EventFeatureSet monté à la main. home/away = dict de features participant."""
    home = {"attack_strength": 1.30, "defense_strength": 0.90} if home is None else home
    away = {"attack_strength": 1.00, "defense_strength": 1.00} if away is None else away
    return EventFeatureSet(
        event_id="e", sport="football", as_of=as_of, feature_set_version="football-1.0",
        event_features={}, participant_features={_H: home, _A: away},
        matchup_features={}, missing_features=set(missing or set()),
    )


# ── Couverture + type + statut global ─────────────────────────────────────────
def test_registered_and_is_a_marketmodel():
    assert isinstance(OneXTwoModel(), MarketModel)
    assert isinstance(manifest.REGISTERED_MARKET_MODELS["MATCH_WINNER"], OneXTwoModel)
    assert manifest.is_market_supported("MATCH_WINNER") is True
    assert manifest.is_market_supported("OVER_UNDER_2_5") is False
    assert manifest.GLOBAL_MODEL_STATUS["MATCH_WINNER"] == DataReadiness.EXPERIMENTAL


# ── Statut EXPERIMENTAL plafonné : JAMAIS SUPPORTED ───────────────────────────
def test_perfect_data_is_experimental_never_supported():
    model = OneXTwoModel()
    readiness = model.assess_data_readiness(_event(), _features())   # données parfaites
    assert readiness == DataReadiness.EXPERIMENTAL
    assert readiness != DataReadiness.SUPPORTED
    pred = model.predict(_event(), _HOME, _features(), _T)
    assert pred.calibration_status == DataReadiness.EXPERIMENTAL
    assert pred.calibration_status != DataReadiness.SUPPORTED


# ── Readiness par événement ───────────────────────────────────────────────────
def test_missing_form_is_insufficient_and_predict_raises():
    model = OneXTwoModel()
    fs = _features(home={}, missing={f"form:{_H}", f"rest_days:{_H}"})   # PSG sans forces
    assert model.assess_data_readiness(_event(), fs) == DataReadiness.INSUFFICIENT_DATA
    with pytest.raises(InsufficientDataError):
        model.predict(_event(), _HOME, fs, _T)


def test_insufficient_form_still_predicts_but_degraded_with_warning():
    model = OneXTwoModel()
    fs = _features(
        home={"attack_strength": 1.1, "defense_strength": 1.0, "form_matches": 2},
        missing={f"form_insufficient:{_H}"},
    )
    assert model.assess_data_readiness(_event(), fs) == DataReadiness.EXPERIMENTAL
    pred = model.predict(_event(), _HOME, fs, _T)
    assert any("historique insuffisant" in w and _H in w for w in pred.explanation.warnings)
    assert pred.data_quality < 1.0                      # dégradé


def test_missing_standings_degrades_with_fallback_warning():
    model = OneXTwoModel()
    fs = _features(missing={f"standings:{_A}"})
    assert model.assess_data_readiness(_event(), fs) == DataReadiness.EXPERIMENTAL
    pred = model.predict(_event(), _HOME, fs, _T)
    assert any("ajustement adversaire désactivé" in w for w in pred.explanation.warnings)
    assert pred.data_quality < 1.0


# ── point_in_time (ADR-004) ───────────────────────────────────────────────────
def test_point_in_time_is_mandatory_never_defaults_to_now():
    with pytest.raises(ValueError):
        OneXTwoModel().predict(_event(), _HOME, _features(), None)  # type: ignore[arg-type]


def test_point_in_time_is_propagated_into_prediction():
    pit = _T + timedelta(hours=3)
    pred = OneXTwoModel().predict(_event(), _HOME, _features(as_of=_T), pit)
    assert pred.point_in_time == pit


def test_features_more_recent_than_point_in_time_is_a_leak():
    # as_of postérieur au point de décision -> fuite temporelle refusée.
    fs = _features(as_of=_T + timedelta(hours=2))
    with pytest.raises(PointInTimeViolationError):
        OneXTwoModel().predict(_event(), _HOME, fs, _T)


# ── Garde-fous marché ─────────────────────────────────────────────────────────
def test_wrong_market_type_is_rejected():
    with pytest.raises(ValueError):
        OneXTwoModel().predict(_event(), CanonicalMarket("OVER_UNDER_2_5", "over"), _features(), _T)


def test_unknown_selection_is_rejected():
    with pytest.raises(ValueError):
        OneXTwoModel().predict(_event(), CanonicalMarket("MATCH_WINNER", "nope"), _features(), _T)


# ── Sortie ────────────────────────────────────────────────────────────────────
def test_selections_sum_to_one():
    preds = OneXTwoModel().predict_selections(_event(), _features(), _T)
    total = sum(preds[s].fair_probability for s in ("home", "draw", "away"))
    assert abs(total - 1.0) < 5e-4


def test_uncertainty_is_not_estimated_no_fake_interval():
    pred = OneXTwoModel().predict(_event(), _HOME, _features(), _T)
    assert pred.uncertainty_status == UncertaintyStatus.NOT_ESTIMATED
    assert pred.probability_low == pred.fair_probability == pred.probability_high
    assert any("absence d'intervalle" in d for d in pred.explanation.confidence_drivers)


def test_explanation_uses_real_model_quantities_not_importances():
    pred = OneXTwoModel().predict(_event(), _HOME, _features(), _T)
    names = {name for name, _ in pred.explanation.top_features}
    assert {"home_expected_goals", "away_expected_goals", "home_attack_strength",
            "home_advantage"} <= names
    assert any("ne décompose pas de contribution par feature" in d
               for d in pred.explanation.confidence_drivers)


def test_current_snapshot_limitation_is_declared():
    pred = OneXTwoModel().predict(_event(), _HOME, _features(), _T)
    assert any("current_snapshot" in w for w in pred.explanation.warnings)


def test_produces_no_ev_odds_or_decision():
    # Périmètre : le contrat MarketPrediction ne porte aucune notion de value.
    pred = OneXTwoModel().predict(_event(), _HOME, _features(), _T)
    forbidden = {"expected_value", "ev", "odds", "decision", "stake", "kelly"}
    assert not (forbidden & set(vars(pred)))
