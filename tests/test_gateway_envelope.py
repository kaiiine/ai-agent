"""Tests de CanonicalEnvelope et de la politique de fraîcheur (arbitrage Vague 0)."""

from __future__ import annotations
from datetime import datetime, timezone

import pytest

from src.agents.quant.gateway.canonical.envelope import (
    CanonicalEnvelope,
    resolve_freshness_basis,
)


def _envelope(**overrides):
    base = dict(
        canonical_id="team:psg",
        sport="football",
        competition_id="competition:football:fra:ligue1",
        season="2025",
        data_type="RESULTS",
        schema_version="football/1.0",
        payload=object(),
        provider="football_data_org",
        provider_entity_id="524",
        event_time=None,
        published_time=None,
        available_to_model_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        data_quality=0.9,
        freshness_score=1.0,
        freshness_basis="fetched_at",
        freshness_degraded=True,
    )
    base.update(overrides)
    return CanonicalEnvelope(**base)


def test_envelope_holds_v2_identity_fields():
    env = _envelope()
    assert env.sport == "football"
    assert env.data_type == "RESULTS"
    assert env.schema_version == "football/1.0"
    assert env.provider_entity_id == "524"
    assert env.stale is False


def test_envelope_rejects_invalid_data_type():
    with pytest.raises(ValueError):
        _envelope(data_type="GOALS")


# --- Politique de fraîcheur : published -> event -> fetched (dégradé) ---

def test_freshness_prefers_published_time():
    pub = datetime(2026, 3, 1, tzinfo=timezone.utc)
    evt = datetime(2026, 2, 1, tzinfo=timezone.utc)
    fetched = datetime(2026, 3, 10, tzinfo=timezone.utc)
    effective, basis, degraded = resolve_freshness_basis(pub, evt, fetched)
    assert (effective, basis, degraded) == (pub, "published_time", False)


def test_freshness_falls_back_to_event_time():
    evt = datetime(2026, 2, 1, tzinfo=timezone.utc)
    fetched = datetime(2026, 3, 10, tzinfo=timezone.utc)
    effective, basis, degraded = resolve_freshness_basis(None, evt, fetched)
    assert (effective, basis, degraded) == (evt, "event_time", False)


def test_freshness_degrades_to_fetched_at_explicitly():
    fetched = datetime(2026, 3, 10, tzinfo=timezone.utc)
    effective, basis, degraded = resolve_freshness_basis(None, None, fetched)
    assert (effective, basis, degraded) == (fetched, "fetched_at", True)
    # Jamais fabriqué : on retombe sur fetched_at mais on le SIGNALE.
    assert degraded is True
