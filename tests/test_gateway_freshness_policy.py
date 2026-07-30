"""Fraîcheur Gateway versionnée : formule, seuils config, frontières temporelles,
timestamp manquant. La fraîcheur est calculée à partir d'un horodatage RÉEL ; une
donnée sans horodatage fiable ne devient jamais « fraîche » par défaut.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.gateway.canonical.envelope import resolve_freshness_basis
from src.agents.quant.gateway.core import quality
from src.agents.quant.gateway.core.freshness_policy import (
    _CONFIG_PATH,
    load_freshness_policy,
    default_freshness_policy,
)

_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


# --- Config versionnée : checksum, chargement, valeurs historiques préservées ----
def test_policy_loads_with_valid_checksum_and_historical_values():
    p = load_freshness_policy()
    assert p.half_life_hours == {"FIXTURES": 12.0, "RESULTS": 24.0, "STANDINGS": 24.0}
    assert p.default_half_life_hours == 12.0
    assert p.live_staleness_tolerance == timedelta(hours=48)


def test_policy_checksum_is_tamper_evident(tmp_path):
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    data["half_life_hours"]["RESULTS"] = 999.0            # falsification sans recalcul du checksum
    bad = tmp_path / "freshness_policy.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_freshness_policy(bad)


def test_policy_rejects_non_positive_half_life(tmp_path):
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    data["half_life_hours"]["RESULTS"] = 0.0
    # recalcul du checksum pour isoler la validation métier (pas la garde checksum)
    import hashlib
    from src.agents.quant.gateway.core.freshness_policy import _CHECKSUM_FIELDS
    payload = {k: data[k] for k in _CHECKSUM_FIELDS}
    data["checksum"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    bad = tmp_path / "freshness_policy.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="half_life_hours"):
        load_freshness_policy(bad)


# --- Formule : frontières temporelles exactes ------------------------------------
def test_freshness_is_one_at_zero_age():
    assert quality.freshness_score(_NOW, _NOW, "RESULTS") == 1.0


def test_freshness_is_half_after_exactly_one_half_life():
    # RESULTS : demi-vie 24h → score 0.5 à 24h pile.
    old = _NOW - timedelta(hours=24)
    assert quality.freshness_score(old, _NOW, "RESULTS") == 0.5


def test_freshness_is_quarter_after_two_half_lives():
    old = _NOW - timedelta(hours=48)
    assert quality.freshness_score(old, _NOW, "RESULTS") == 0.25


def test_unknown_data_type_uses_default_half_life():
    # data_type absent de la table → demi-vie par défaut (12h), pas une valeur fabriquée.
    old = _NOW - timedelta(hours=12)
    assert quality.freshness_score(old, _NOW, "MYSTERY_TYPE") == 0.5


def test_future_effective_time_is_clamped_not_amplified():
    # Un horodatage dans le futur (âge négatif) ne « sur-fraîchit » pas : plafonné à 1.0.
    future = _NOW + timedelta(hours=10)
    assert quality.freshness_score(future, _NOW, "RESULTS") == 1.0


def test_injected_policy_overrides_default(tmp_path):
    from src.agents.quant.gateway.core.freshness_policy import FreshnessPolicy
    fast = FreshnessPolicy(
        config_version="test", effective_from="2026-01-01", checksum="x",
        half_life_hours={"RESULTS": 1.0}, default_half_life_hours=1.0,
        live_staleness_tolerance_hours=48.0,
    )
    old = _NOW - timedelta(hours=1)
    assert quality.freshness_score(old, _NOW, "RESULTS", policy=fast) == 0.5


# --- Timestamp manquant : jamais de fraîcheur favorable inventée -----------------
def test_missing_published_and_event_falls_back_to_fetched_with_degraded_flag():
    fetched = _NOW - timedelta(hours=1)
    effective, basis, degraded = resolve_freshness_basis(
        published_time=None, event_time=None, fetched_at=fetched
    )
    assert effective == fetched
    assert basis == "fetched_at"
    assert degraded is True                              # signalé, jamais masqué


def test_published_time_preferred_over_event_and_fetched():
    published = _NOW - timedelta(hours=2)
    event = _NOW - timedelta(hours=5)
    fetched = _NOW
    effective, basis, degraded = resolve_freshness_basis(published, event, fetched)
    assert effective == published and basis == "published_time" and degraded is False


def test_degraded_basis_does_not_inflate_freshness():
    # Donnée réellement ancienne mais sans published/event : on tombe sur fetched_at
    # (degraded) — la fraîcheur reflète fetched_at, jamais un 1.0 de complaisance non
    # justifié ; le flag degraded prévient le consommateur que la base est faible.
    fetched = _NOW - timedelta(hours=24)
    effective, basis, degraded = resolve_freshness_basis(None, None, fetched)
    assert degraded is True
    assert quality.freshness_score(effective, _NOW, "RESULTS") == 0.5


def test_default_policy_singleton_is_cached():
    assert default_freshness_policy() is default_freshness_policy()
