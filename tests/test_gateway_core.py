"""Tests core gateway — invariants d'identité, point-in-time store et cache.

Filet de non-régression Vague 0 pour les propriétés structurelles qui ne
dépendent d'aucun provider : résolution d'identité typée (dont l'ex-bug de
collision v1), idempotence du store, scoping par saison, indépendance
cache / store (GW-NFR-008).
"""

from __future__ import annotations
from datetime import datetime, timezone


def _resolver():
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
    from src.agents.quant.gateway.core.identity_data import TEAMS
    # Depuis C5, le résolveur ne contient que des équipes (les compétitions vivent
    # dans competition_registry + coverage_registry, plus dans l'identité).
    return IdentityResolver(TEAMS)


def test_identity_resolve_roundtrip():
    r = _resolver()
    assert r.resolve("team:football:fra:psg", "api_sports") == "85"
    assert r.resolve("team:football:fra:psg", "football_data_org") == "524"
    assert r.canonicalize("api_sports", "85", "team") == ("team:football:fra:psg", "RESOLVED")
    assert r.canonicalize("football_data_org", "524", "team") == ("team:football:fra:psg", "RESOLVED")


def test_canonicalize_unknown_is_unresolved():
    r = _resolver()
    assert r.canonicalize("api_sports", "999999", "team") == (None, "UNRESOLVED")


def test_collision_avoided_by_registry_separation():
    """Ex-bug v1 : chez api_sports l'id '39' désigne l'équipe Wolves ET la ligue
    Premier League. Depuis C5 la collision est impossible par SÉPARATION : les
    compétitions ne sont plus dans le résolveur d'identité (elles vivent dans
    competition_registry + coverage_registry). Le résolveur ne connaît que
    l'équipe ; l'id '39' côté compétition n'y existe pas."""
    r = _resolver()
    assert r.canonicalize("api_sports", "39", "team") == ("team:football:eng:wolves", "RESOLVED")
    # La compétition n'est pas dans le résolveur -> aucune collision possible.
    assert r.canonicalize("api_sports", "39", "competition") == (None, "UNRESOLVED")
    assert r.resolve("competition:football:eng:premier_league", "api_sports") is None


def test_flat_canonical_id_is_rejected():
    """GW-FR-008 : un id non typé (plat) est refusé à la construction du registre."""
    import pytest
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver, CanonicalEntity
    with pytest.raises(ValueError):
        IdentityResolver([CanonicalEntity("team:psg", "PSG", [], {"api_sports": "85"})])


def test_store_dedup_content_hash(tmp_path, monkeypatch):
    from src.agents.quant.gateway.core import point_in_time_store as store
    monkeypatch.setattr(store, "STORE_DB", tmp_path / "store.db")

    payload = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:psg", "rank": 1}]}
    now = datetime.now(timezone.utc)
    first = store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", payload, "fp", now, "football/1.0")
    second = store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", payload, "fp", now, "football/1.0")

    assert first.resulted_in_new_snapshot is True
    assert second.resulted_in_new_snapshot is False  # payload identique -> pas de doublon


def test_last_snapshot_is_season_scoped(tmp_path, monkeypatch):
    """Ex-bug v1 : un snapshot 2024 ne doit jamais servir de recours pour 2025."""
    from src.agents.quant.gateway.core import point_in_time_store as store
    monkeypatch.setattr(store, "STORE_DB", tmp_path / "store.db")

    now = datetime.now(timezone.utc)
    p2024 = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:psg", "rank": 5}]}
    p2025 = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:psg", "rank": 1}]}
    store.write("football", "competition:football:fra:ligue1:2024", "standings", "api_sports", p2024, "fp24", now, "football/1.0")
    store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", p2025, "fp25", now, "football/1.0")

    snap_2025 = store.last_snapshot("football", "competition:football:fra:ligue1:2025", "standings")
    snap_2024 = store.last_snapshot("football", "competition:football:fra:ligue1:2024", "standings")
    assert snap_2025["payload"]["standings"][0]["rank"] == 1
    assert snap_2024["payload"]["standings"][0]["rank"] == 5


def test_cache_purge_preserves_store(tmp_path, monkeypatch):
    """GW-NFR-008 : purger le cache opérationnel n'efface jamais le point-in-time store."""
    from src.agents.quant.gateway.core import point_in_time_store as store
    from src.agents.quant.gateway.cache import operational_cache as cache
    monkeypatch.setattr(store, "STORE_DB", tmp_path / "store.db")
    monkeypatch.setattr(cache, "CACHE_DB", tmp_path / "cache.db")

    now = datetime.now(timezone.utc)
    payload = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:psg", "rank": 1}]}
    store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", payload, "fp", now, "football/1.0")

    cache.cache_set("k1", "standings", {"x": 1})
    assert cache.cache_get("k1", "standings") == {"x": 1}

    monkeypatch.setitem(cache.TTL_SECONDS, "standings", 0)  # force l'expiration
    purged = cache.purge_expired()

    assert purged == 1
    assert cache.cache_get("k1", "standings") is None            # cache vidé
    assert store.last_snapshot("football", "competition:football:fra:ligue1:2025", "standings") is not None  # store intact


# ── C4 : store point-in-time — 5 horodatages, schema_version, provider_entity_id ──

def test_store_persists_schema_version_and_provenance(tmp_path, monkeypatch):
    from src.agents.quant.gateway.core import point_in_time_store as store
    monkeypatch.setattr(store, "STORE_DB", tmp_path / "store.db")

    fetched = datetime(2026, 5, 30, 20, 20, tzinfo=timezone.utc)
    ingested = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    payload = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:football:fra:psg", "rank": 1}]}
    store.write(
        "football", "competition:football:fra:ligue1:2025", "standings", "football_data_org",
        payload, "fp", fetched, "football/1.0",
        provider_entity_id="FL1", event_time=None, published_time=None,
        available_to_model_time=fetched, ingested_at=ingested,
    )
    snap = store.last_snapshot("football", "competition:football:fra:ligue1:2025", "standings")
    assert snap["schema_version"] == "football/1.0"
    assert snap["provider_entity_id"] == "FL1"
    assert snap["event_time"] is None          # None explicite, jamais fabriqué
    assert snap["published_time"] is None
    assert snap["available_to_model_time"] == fetched.isoformat()
    assert snap["ingested_at"] == ingested.isoformat()


def test_content_hash_includes_schema_version(tmp_path, monkeypatch):
    """GW-NFR-002 : même payload sous deux schémas différents -> deux snapshots, jamais une dédup."""
    from src.agents.quant.gateway.core import point_in_time_store as store
    monkeypatch.setattr(store, "STORE_DB", tmp_path / "store.db")

    # Deux fetchs distincts (le schéma a changé entre les deux) — fetched_at diffère,
    # comme en production (un fetch a un seul schema_version courant).
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    payload = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:football:fra:psg", "rank": 1}]}
    e1 = store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", payload, "fp", t1, "football/1.0")
    e2 = store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", payload, "fp", t2, "football/2.0")
    assert e1.resulted_in_new_snapshot is True
    assert e2.resulted_in_new_snapshot is True   # schema différent -> pas de dédup
    assert e1.content_hash != e2.content_hash     # GW-NFR-002 : le hash inclut schema_version


def test_fallback_rejects_incompatible_schema(tmp_path, monkeypatch):
    """GW-FR-009 : le dernier snapshot sous un schéma incompatible n'est jamais réinterprété."""
    import pytest
    from src.agents.quant.gateway.core import point_in_time_store as store, decision_log, fallback_chain
    from src.agents.quant.gateway.cache import operational_cache
    from src.agents.quant.gateway.registries import provider_coverage_registry
    from src.agents.quant.gateway.core.fallback_chain import fetch_league_data
    from src.agents.quant.gateway.core.errors import NoDataAvailableError
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
    from src.agents.quant.gateway.core.identity_data import TEAMS

    monkeypatch.setattr(store, "STORE_DB", tmp_path / "store.db")
    monkeypatch.setattr(operational_cache, "CACHE_DB", tmp_path / "cache.db")
    monkeypatch.setattr(decision_log, "LOG_FILE", tmp_path / "log")
    monkeypatch.setattr(provider_coverage_registry, "COVERAGE_DB", tmp_path / "cov.db")  # coverage vide -> aucun éligible
    monkeypatch.setattr(fallback_chain, "_request_counts", {})

    league = "competition:football:fra:ligue1"
    season = "1999"
    payload = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:football:fra:psg", "rank": 1}]}
    # Snapshot stocké sous l'axe data_type "STANDINGS", schéma incompatible.
    store.write("football", f"{league}:{season}", "STANDINGS", "football_data_org",
                payload, "fp", datetime.now(timezone.utc), "football/0.1")

    resolver = IdentityResolver(TEAMS)
    with pytest.raises(NoDataAvailableError):
        fetch_league_data(
            sport="football", data_type="STANDINGS",
            league_canonical_id=league, season=season, resolver=resolver,
        )
