"""Tests de la migration one-shot des snapshots v1 (C6)."""

from __future__ import annotations
import json
import sqlite3

from src.agents.quant.gateway.core import snapshot_migration as mig
from src.agents.quant.gateway.core import point_in_time_store as store


def _v1_db(tmp_path):
    """Crée une base au schéma v1 (axe 'endpoint', IDs plats, sans schema_version)."""
    db = tmp_path / "store.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE data_snapshot (sport TEXT, entity_id TEXT, endpoint TEXT, provider TEXT,
        fetched_at TEXT, content_hash TEXT, payload TEXT,
        PRIMARY KEY (sport, entity_id, endpoint, provider, fetched_at))""")
    conn.execute("""CREATE TABLE fetch_event (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, endpoint TEXT,
        request_fingerprint TEXT, content_hash TEXT, fetched_at TEXT, resulted_in_new_snapshot INTEGER)""")
    return db, conn


def test_migration_splits_and_remaps(tmp_path):
    db, conn = _v1_db(tmp_path)
    # Snapshot fixtures v1 : 1 match joué (RESULTS) + 1 à venir (FIXTURES), IDs plats.
    fixtures_payload = {"kind": "fixtures", "standings": [], "matches": [
        {"canonical_match_id": "fdo:1", "league_id": "league:ligue1", "season": "2025",
         "home_team_id": "team:psg", "away_team_id": "team:monaco", "kickoff": "2026-03-06T19:45:00+00:00",
         "status": "FINISHED", "goals_home": 1, "goals_away": 3},
        {"canonical_match_id": "fdo:2", "league_id": "league:ligue1", "season": "2025",
         "home_team_id": "team:lens", "away_team_id": "team:lille", "kickoff": "2026-08-01T19:00:00+00:00",
         "status": "SCHEDULED", "goals_home": None, "goals_away": None},
    ]}
    conn.execute("INSERT INTO data_snapshot VALUES (?,?,?,?,?,?,?)",
                 ("football", "league:ligue1:2025", "fixtures", "football_data_org",
                  "2026-07-24T12:00:00+00:00", "oldhash", json.dumps(fixtures_payload)))
    conn.commit(); conn.close()

    report = mig.migrate(db_path=db, apply=True)

    assert report.backup_path is not None
    assert len(report.migrated) == 1
    assert report.skipped == []

    # Le snapshot fixtures a produit 2 snapshots : RESULTS (1 match) + FIXTURES (1 match).
    new = {e["data_type"]: e for e in report.migrated[0]["new"]}
    assert new["RESULTS"]["n_matches"] == 1
    assert new["FIXTURES"]["n_matches"] == 1
    assert new["RESULTS"]["new_entity"] == "competition:football:fra:ligue1:2025"

    # Les nouveaux snapshots existent, IDs typés, schema_version posé.
    snap = store.last_snapshot("football", "competition:football:fra:ligue1:2025", "RESULTS", db_path=db)
    assert snap["schema_version"] == "football/1.0"
    assert snap["payload"]["matches"][0]["home_team_id"] == "team:football:fra:psg"
    assert snap["payload"]["matches"][0]["away_team_id"] == "team:football:fra:monaco"


def test_migration_preserves_standings_and_hash_changes(tmp_path):
    db, conn = _v1_db(tmp_path)
    standings_payload = {"kind": "standings", "matches": [], "standings": [
        {"team_id": "team:psg", "rank": 1, "played": 34, "points": 85},
        {"team_id": "team:lens", "rank": 2, "played": 34, "points": 78},
    ]}
    conn.execute("INSERT INTO data_snapshot VALUES (?,?,?,?,?,?,?)",
                 ("football", "league:ligue1:2025", "standings", "football_data_org",
                  "2026-07-24T12:00:00+00:00", "oldhash_standings", json.dumps(standings_payload)))
    conn.commit(); conn.close()

    report = mig.migrate(db_path=db, apply=True)
    entry = report.migrated[0]
    new = entry["new"][0]
    assert new["data_type"] == "STANDINGS"
    assert new["n_standings"] == 2
    # Le content_hash change (schema + IDs remappés), mais les faits sont préservés.
    assert new["new_hash"] != entry["old_hash"]
    snap = store.last_snapshot("football", "competition:football:fra:ligue1:2025", "STANDINGS", db_path=db)
    assert {r["team_id"] for r in snap["payload"]["standings"]} == {
        "team:football:fra:psg", "team:football:fra:lens",
    }


def test_migration_skips_unresolvable_ids(tmp_path):
    db, conn = _v1_db(tmp_path)
    # Équipe reléguée absente du registre courant -> non résoluble -> snapshot sauté.
    payload = {"kind": "standings", "matches": [], "standings": [
        {"team_id": "team:some_relegated_club", "rank": 1, "played": 34, "points": 85},
    ]}
    conn.execute("INSERT INTO data_snapshot VALUES (?,?,?,?,?,?,?)",
                 ("football", "league:ligue1:2025", "standings", "football_data_org",
                  "2026-07-24T12:00:00+00:00", "h", json.dumps(payload)))
    conn.commit(); conn.close()

    report = mig.migrate(db_path=db, apply=True)
    assert report.migrated == []
    assert len(report.skipped) == 1
    assert "team:some_relegated_club" in report.skipped[0]["unresolved"]


def test_migration_is_append_only(tmp_path):
    """Les lignes v1 ne sont jamais supprimées."""
    db, conn = _v1_db(tmp_path)
    payload = {"kind": "standings", "matches": [], "standings": [
        {"team_id": "team:psg", "rank": 1, "played": 34, "points": 85}]}
    conn.execute("INSERT INTO data_snapshot VALUES (?,?,?,?,?,?,?)",
                 ("football", "league:ligue1:2025", "standings", "football_data_org",
                  "2026-07-24T12:00:00+00:00", "h", json.dumps(payload)))
    conn.commit(); conn.close()

    mig.migrate(db_path=db, apply=True)
    conn = sqlite3.connect(db)
    # La ligne v1 (schema_version NULL) est toujours là + la nouvelle (football/1.0).
    n_v1 = conn.execute("SELECT COUNT(*) FROM data_snapshot WHERE schema_version IS NULL").fetchone()[0]
    n_new = conn.execute("SELECT COUNT(*) FROM data_snapshot WHERE schema_version = 'football/1.0'").fetchone()[0]
    conn.close()
    assert n_v1 == 1   # jamais supprimée
    assert n_new == 1
