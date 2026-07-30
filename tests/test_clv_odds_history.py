"""odds_history (BE-FR-015) + CLV point-in-time.

Prouve : (1) Decimal obligatoire (jamais float) ; (2) CLV réelle sur paire
décision/clôture ; (3) point-in-time strict (clôture après décision) ; (4) absence
de paire -> NOT_YET_MEASURABLE, mean_clv=None (jamais 0) ; (5) store append-only
round-trip Decimal ; (6) jamais ~/.axon.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.clv import (
    MEASURABLE,
    NOT_YET_MEASURABLE,
    JsonlOddsHistoryStore,
    ObservationPhase,
    OddsObservation,
    clv_readiness,
    compute_clv,
)

_T0 = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _obs(phase, odds, *, when=_T0, selection="home"):
    return OddsObservation(
        event_id="event:football:fra:ligue1:2026-03-01:psg-om",
        market_type="MATCH_WINNER", selection=selection, bookmaker="winamax",
        decimal_odds=Decimal(odds), observed_at=when, phase=phase,
        source="winamax", source_event_id="12345", run_id="run-1",
    )


# --- Decimal obligatoire ---------------------------------------------------------
def test_float_odds_are_rejected():
    with pytest.raises(TypeError):
        OddsObservation(                               # float interdit (donnée sensible)
            event_id="e", market_type="MATCH_WINNER", selection="home", bookmaker="winamax",
            decimal_odds=2.10, observed_at=_T0, phase=ObservationPhase.DECISION, source="winamax",
        )


def test_odds_must_be_greater_than_one():
    with pytest.raises(ValueError):
        _obs(ObservationPhase.DECISION, "0.90")


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        OddsObservation(
            event_id="e", market_type="MATCH_WINNER", selection="home", bookmaker="winamax",
            decimal_odds=Decimal("2.0"), observed_at=datetime(2026, 3, 1, 12, 0),  # naive
            phase=ObservationPhase.DECISION, source="winamax",
        )


# --- CLV réelle point-in-time ----------------------------------------------------
def test_clv_positive_when_decision_odds_beat_close():
    decision = _obs(ObservationPhase.DECISION, "2.10", when=_T0)
    closing = _obs(ObservationPhase.CLOSING, "1.90", when=_T0 + timedelta(hours=2))
    r = compute_clv(decision, closing)
    assert r.clv == Decimal("2.10") / Decimal("1.90") - Decimal("1")
    assert r.beat_close is True


def test_clv_requires_closing_strictly_after_decision():
    decision = _obs(ObservationPhase.DECISION, "2.10", when=_T0)
    closing_before = _obs(ObservationPhase.CLOSING, "1.90", when=_T0 - timedelta(hours=1))
    with pytest.raises(ValueError, match="point-in-time"):
        compute_clv(decision, closing_before)


def test_clv_rejects_mismatched_markets():
    decision = _obs(ObservationPhase.DECISION, "2.10", selection="home")
    closing = _obs(ObservationPhase.CLOSING, "1.90", selection="away",
                   when=_T0 + timedelta(hours=1))
    with pytest.raises(ValueError, match="même marché"):
        compute_clv(decision, closing)


# --- Readiness : absence de paire = NOT_YET_MEASURABLE, jamais 0 -----------------
def test_no_pairs_is_not_yet_measurable_not_zero():
    only_decisions = [_obs(ObservationPhase.DECISION, "2.10")]
    r = clv_readiness(only_decisions)
    assert r.status == NOT_YET_MEASURABLE
    assert r.mean_clv is None                          # jamais 0
    assert r.n_complete_pairs == 0


def test_empty_history_is_not_yet_measurable():
    r = clv_readiness([])
    assert r.status == NOT_YET_MEASURABLE and r.mean_clv is None


def test_complete_pair_is_measurable():
    obs = [
        _obs(ObservationPhase.DECISION, "2.10", when=_T0),
        _obs(ObservationPhase.CLOSING, "1.90", when=_T0 + timedelta(hours=3)),
    ]
    r = clv_readiness(obs)
    assert r.status == MEASURABLE
    assert r.n_complete_pairs == 1
    assert r.mean_clv is not None and r.mean_clv > 0


# --- Store append-only, round-trip Decimal, jamais ~/.axon ----------------------
def test_store_roundtrip_preserves_decimal(tmp_path):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    o = _obs(ObservationPhase.DECISION, "2.10")
    store.append(o)
    store.append(_obs(ObservationPhase.CLOSING, "1.95", when=_T0 + timedelta(hours=2)))
    loaded = store.all()
    assert len(loaded) == 2
    assert loaded[0].decimal_odds == Decimal("2.10")   # Decimal exact, pas float
    assert isinstance(loaded[0].decimal_odds, Decimal)


def test_store_refuses_home_axon_path():
    with pytest.raises(ValueError, match="axon"):
        JsonlOddsHistoryStore("~/.axon/odds.jsonl")


def test_store_readiness_from_persisted_observations(tmp_path):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    store.append(_obs(ObservationPhase.DECISION, "2.10", when=_T0))
    store.append(_obs(ObservationPhase.CLOSING, "1.90", when=_T0 + timedelta(hours=2)))
    r = clv_readiness(store.all())
    assert r.status == MEASURABLE and r.n_complete_pairs == 1
