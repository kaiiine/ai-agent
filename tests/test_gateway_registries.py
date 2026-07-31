"""Tests des registres séparés — competition (identité) et coverage (GW-FR-002/003/005)."""

from __future__ import annotations
from datetime import datetime, timezone

import pytest

from src.agents.quant.gateway.registries import competition_registry as cr
from src.agents.quant.gateway.registries import provider_coverage_registry as pcr
from src.agents.quant.gateway.registries.provider_coverage_registry import (
    CoverageStatus,
    ProviderCompetitionCoverage,
)


# ── Competition Registry : identité seule, canonical_id typé, aucun ID provider ──

def test_competition_registry_loads_typed_ids():
    l1 = cr.get_competition("competition:football:fra:ligue1")
    pl = cr.get_competition("competition:football:eng:premier_league")
    assert l1 is not None and l1.name == "Ligue 1" and l1.tier == 1 and l1.status == "active"
    assert pl is not None and pl.country_code == "GB"


def test_competition_identity_carries_no_provider_id():
    # GW-FR-002 : l'identité de compétition ne porte AUCUN identifiant provider.
    from dataclasses import fields
    field_names = {f.name for f in fields(cr.Competition)}
    assert not any("provider" in n or n == "identities" for n in field_names)
    assert field_names == {
        "canonical_id", "sport", "name", "country_code", "competition_type", "tier", "status",
    }


def test_active_competitions_filter():
    active = cr.active_competitions("football")
    assert {c.canonical_id for c in active} == {
        "competition:football:fra:ligue1",
        "competition:football:eng:premier_league",
        # Onboardées via données réelles football-data.org (identités vérifiées en direct).
        "competition:football:ita:serie_a",
        "competition:football:esp:laliga",
        "competition:football:deu:bundesliga",
        "competition:football:eng:championship",
        "competition:football:nld:eredivisie",
        "competition:football:prt:primeira_liga",
    }


# ── Provider Coverage Registry : CRUD + filtrage GW-FR-005 ──────────────────────

def _entry(status, provider="football_data_org", data_type="STANDINGS", season="2025", method="live_call"):
    return ProviderCompetitionCoverage(
        provider=provider,
        competition_id="competition:football:fra:ligue1",
        provider_competition_id="FL1",
        season=season,
        data_type=data_type,
        status=status,
        verified_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        verification_method=method,
    )


def test_coverage_record_and_get(tmp_path):
    db = tmp_path / "cov.db"
    entry = _entry(CoverageStatus.FULL)
    pcr.record_coverage(entry, db_path=db)
    got = pcr.get_coverage("football_data_org", entry.competition_id, "2025", "STANDINGS", db_path=db)
    assert got is not None
    assert got.status == CoverageStatus.FULL
    assert got.provider_competition_id == "FL1"


def test_usable_providers_excludes_unverified_and_absent(tmp_path):
    db = tmp_path / "cov.db"
    pcr.record_coverage(_entry(CoverageStatus.FULL, provider="football_data_org"), db_path=db)
    pcr.record_coverage(_entry(CoverageStatus.UNVERIFIED, provider="thesportsdb", method="manual"), db_path=db)
    pcr.record_coverage(_entry(CoverageStatus.ABSENT, provider="api_sports"), db_path=db)

    usable = pcr.usable_providers("competition:football:fra:ligue1", "2025", "STANDINGS", db_path=db)
    assert usable == ["football_data_org"]  # UNVERIFIED et ABSENT écartés (GW-FR-005)


def test_verification_method_is_validated():
    with pytest.raises(ValueError):
        _entry(CoverageStatus.FULL, method="rumeur")


def test_all_coverage_returns_entries_for_competition_season(tmp_path):
    db = tmp_path / "cov.db"
    pcr.seed(db_path=db)
    entries = pcr.all_coverage("competition:football:fra:ligue1", "2025", db_path=db)
    assert {e.data_type for e in entries} == {"FIXTURES", "RESULTS", "STANDINGS"}
    # api_sports 2025 est ABSENT (tier gratuit) et présent dans le rapport (diagnostic).
    absent = [e for e in entries if e.provider == "api_sports" and e.status == CoverageStatus.ABSENT]
    assert len(absent) == 3


# ── Baseline seed ───────────────────────────────────────────────────────────────

def test_seed_materializes_known_coverage(tmp_path):
    db = tmp_path / "cov.db"
    n = pcr.seed(db_path=db)
    assert n > 0
    # football-data.org couvre la Ligue 1 2025 (STANDINGS) en FULL...
    assert "football_data_org" in pcr.usable_providers(
        "competition:football:fra:ligue1", "2025", "STANDINGS", db_path=db
    )
    # ...mais API-Sports est ABSENT en 2025 (tier gratuit) -> jamais utilisable
    assert "api_sports" not in pcr.usable_providers(
        "competition:football:fra:ligue1", "2025", "STANDINGS", db_path=db
    )
    # PL matchs 2025 : UNVERIFIED -> aucun provider utilisable
    assert pcr.usable_providers(
        "competition:football:eng:premier_league", "2025", "RESULTS", db_path=db
    ) == []


# ── Vérification par appel réel (provider mocké, aucun réseau) ──────────────────

def test_verify_records_live_call_full(tmp_path, monkeypatch):
    from src.agents.quant.gateway.registries import coverage_verification as cv
    from src.agents.quant.gateway.core.provider_registry import REGISTRY
    from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse

    provider = REGISTRY["football_data_org"].provider
    monkeypatch.setattr(provider, "is_available", lambda sport, season: True)
    monkeypatch.setattr(
        provider, "fetch_standings",
        lambda sport, pid, season: RawProviderResponse(
            payload={"standings": [{"table": [{"x": 1}]}]},
            provider="football_data_org",
            fetched_at=datetime.now(timezone.utc),
        ),
    )
    db = tmp_path / "cov.db"
    entry = cv.verify("football_data_org", "competition:football:fra:ligue1", "FL1", "2025", "STANDINGS", db_path=db)
    assert entry.status == CoverageStatus.FULL
    assert entry.verification_method == "live_call"
    assert pcr.get_coverage("football_data_org", "competition:football:fra:ligue1", "2025", "STANDINGS", db_path=db).status == CoverageStatus.FULL


def test_verify_records_absent_when_season_unavailable(tmp_path, monkeypatch):
    from src.agents.quant.gateway.registries import coverage_verification as cv
    from src.agents.quant.gateway.core.provider_registry import REGISTRY

    provider = REGISTRY["api_sports"].provider
    monkeypatch.setattr(provider, "is_available", lambda sport, season: False)  # tier gratuit bloque 2025
    entry = cv.verify("api_sports", "competition:football:fra:ligue1", "61", "2025", "STANDINGS", db_path=tmp_path / "c.db")
    assert entry.status == CoverageStatus.ABSENT
    assert entry.verification_method == "live_call"  # tenté en direct, constaté absent
