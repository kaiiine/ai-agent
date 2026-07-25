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
    from src.agents.quant.gateway.core.identity_data import LEAGUES, TEAMS
    return IdentityResolver(LEAGUES + TEAMS)


def test_identity_resolve_roundtrip():
    r = _resolver()
    assert r.resolve("team:football:fra:psg", "api_sports") == "85"
    assert r.resolve("team:football:fra:psg", "football_data_org") == "524"
    assert r.canonicalize("api_sports", "85", "team") == ("team:football:fra:psg", "RESOLVED")
    assert r.canonicalize("football_data_org", "524", "team") == ("team:football:fra:psg", "RESOLVED")


def test_canonicalize_unknown_is_unresolved():
    r = _resolver()
    assert r.canonicalize("api_sports", "999999", "team") == (None, "UNRESOLVED")


def test_identity_typed_collision_wolves_vs_premier_league():
    """Ex-bug v1 : chez api_sports l'id '39' désigne l'équipe Wolves ET la ligue
    Premier League. Le typage par entity_type (team vs competition) lève l'ambiguïté."""
    r = _resolver()
    assert r.resolve("team:football:eng:wolves", "api_sports") == "39"
    assert r.resolve("competition:football:eng:premier_league", "api_sports") == "39"
    assert r.canonicalize("api_sports", "39", "team") == ("team:football:eng:wolves", "RESOLVED")
    assert r.canonicalize("api_sports", "39", "competition") == ("competition:football:eng:premier_league", "RESOLVED")


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
    first = store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", payload, "fp", now)
    second = store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", payload, "fp", now)

    assert first.resulted_in_new_snapshot is True
    assert second.resulted_in_new_snapshot is False  # payload identique -> pas de doublon


def test_last_snapshot_is_season_scoped(tmp_path, monkeypatch):
    """Ex-bug v1 : un snapshot 2024 ne doit jamais servir de recours pour 2025."""
    from src.agents.quant.gateway.core import point_in_time_store as store
    monkeypatch.setattr(store, "STORE_DB", tmp_path / "store.db")

    now = datetime.now(timezone.utc)
    p2024 = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:psg", "rank": 5}]}
    p2025 = {"kind": "standings", "matches": [], "standings": [{"team_id": "team:psg", "rank": 1}]}
    store.write("football", "competition:football:fra:ligue1:2024", "standings", "api_sports", p2024, "fp24", now)
    store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", p2025, "fp25", now)

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
    store.write("football", "competition:football:fra:ligue1:2025", "standings", "football_data_org", payload, "fp", now)

    cache.cache_set("k1", "standings", {"x": 1})
    assert cache.cache_get("k1", "standings") == {"x": 1}

    monkeypatch.setitem(cache.TTL_SECONDS, "standings", 0)  # force l'expiration
    purged = cache.purge_expired()

    assert purged == 1
    assert cache.cache_get("k1", "standings") is None            # cache vidé
    assert store.last_snapshot("football", "competition:football:fra:ligue1:2025", "standings") is not None  # store intact
