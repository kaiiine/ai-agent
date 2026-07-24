"""Persistance point-in-time — jamais purgée, jamais mise à jour en place.

Deux tables : fetch_event trace CHAQUE appel provider (audit complet),
data_snapshot ne stocke un nouveau payload que si son content_hash diffère
du dernier connu pour la même clé de partition — évite d'accumuler des
milliers de snapshots identiques lors d'un polling périodique.
"""

from __future__ import annotations
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

STORE_DB = Path.home() / ".axon" / "sports_point_in_time.db"


@dataclass(frozen=True)
class FetchEvent:
    provider: str
    endpoint: str
    request_fingerprint: str
    content_hash: str
    fetched_at: datetime
    resulted_in_new_snapshot: bool


def _connection() -> sqlite3.Connection:
    STORE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STORE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT, endpoint TEXT, request_fingerprint TEXT,
            content_hash TEXT, fetched_at TEXT, resulted_in_new_snapshot INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_snapshot (
            sport TEXT, entity_id TEXT, endpoint TEXT, provider TEXT,
            fetched_at TEXT, content_hash TEXT, payload TEXT,
            PRIMARY KEY (sport, entity_id, endpoint, provider, fetched_at)
        )
    """)
    return conn


def _hash_payload(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _last_content_hash(conn: sqlite3.Connection, sport: str, entity_id: str, endpoint: str, provider: str) -> str | None:
    row = conn.execute(
        "SELECT content_hash FROM data_snapshot WHERE sport=? AND entity_id=? AND endpoint=? AND provider=? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (sport, entity_id, endpoint, provider),
    ).fetchone()
    return row[0] if row else None


def write(
    sport: str,
    entity_id: str,
    endpoint: str,
    provider: str,
    payload: dict,
    request_fingerprint: str,
    fetched_at: datetime,
) -> FetchEvent:
    """Trace l'appel (toujours), écrit le snapshot seulement si le contenu a changé."""
    conn = _connection()
    try:
        content_hash = _hash_payload(payload)
        previous_hash = _last_content_hash(conn, sport, entity_id, endpoint, provider)
        is_new = content_hash != previous_hash

        if is_new:
            conn.execute(
                "INSERT INTO data_snapshot (sport, entity_id, endpoint, provider, fetched_at, content_hash, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sport, entity_id, endpoint, provider, fetched_at.isoformat(), content_hash, json.dumps(payload)),
            )
        conn.execute(
            "INSERT INTO fetch_event "
            "(provider, endpoint, request_fingerprint, content_hash, fetched_at, resulted_in_new_snapshot) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (provider, endpoint, request_fingerprint, content_hash, fetched_at.isoformat(), int(is_new)),
        )
        conn.commit()
        return FetchEvent(provider, endpoint, request_fingerprint, content_hash, fetched_at, is_new)
    finally:
        conn.close()


def last_snapshot(sport: str, entity_id: str, endpoint: str, provider: str | None = None) -> dict | None:
    """Dernier payload connu — recours final du fallback_chain quand tous les providers échouent."""
    conn = _connection()
    try:
        if provider:
            query = (
                "SELECT payload, fetched_at, provider FROM data_snapshot "
                "WHERE sport=? AND entity_id=? AND endpoint=? AND provider=? ORDER BY fetched_at DESC LIMIT 1"
            )
            params = (sport, entity_id, endpoint, provider)
        else:
            query = (
                "SELECT payload, fetched_at, provider FROM data_snapshot "
                "WHERE sport=? AND entity_id=? AND endpoint=? ORDER BY fetched_at DESC LIMIT 1"
            )
            params = (sport, entity_id, endpoint)
        row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        return {"payload": json.loads(row[0]), "fetched_at": row[1], "provider": row[2]}
    finally:
        conn.close()
