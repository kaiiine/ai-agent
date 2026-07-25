"""Persistance point-in-time — jamais purgée, jamais mise à jour en place.

Deux tables : fetch_event trace CHAQUE appel provider (audit complet),
data_snapshot ne stocke un nouveau payload que si son content_hash diffère
du dernier connu pour la même partition logique — évite d'accumuler des
milliers de snapshots identiques lors d'un polling périodique.

Chaque snapshot conserve les 5 horodatages point-in-time distincts (ADR-004 :
event_time, published_time, available_to_model_time, fetched_at, ingested_at),
son schema_version (ADR-009) et le provider_entity_id d'origine (GW-NFR-007
auditabilité). schema_version entre dans le content_hash (GW-NFR-002) et dans
la partition logique (dédup/lecture) : deux schémas différents ne se
dédupliquent jamais l'un contre l'autre.

Note migration : la PK SQL reste (sport, entity_id, endpoint, provider,
fetched_at) — les nouvelles colonnes sont ajoutées par ALTER (ADD COLUMN) sur
une base existante. La réécriture SÉMANTIQUE des anciens snapshots (peupler
sport/data_type/schema_version des lignes v1) est le travail de C6.
"""

from __future__ import annotations
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

STORE_DB = Path.home() / ".axon" / "sports_point_in_time.db"

# Colonnes ajoutées en C4 (migrables par ADD COLUMN sur une base v1 existante),
# par table.
_ADDED_COLUMNS = {
    "data_snapshot": [
        "schema_version TEXT",
        "provider_entity_id TEXT",
        "event_time TEXT",
        "published_time TEXT",
        "available_to_model_time TEXT",
        "ingested_at TEXT",
    ],
    "fetch_event": [
        "schema_version TEXT",
    ],
}


@dataclass(frozen=True)
class FetchEvent:
    provider: str
    endpoint: str
    request_fingerprint: str
    content_hash: str
    fetched_at: datetime
    resulted_in_new_snapshot: bool


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes C4 manquantes aux tables v1 existantes (data_snapshot ET fetch_event)."""
    for table, column_defs in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column_def in column_defs:
            name = column_def.split()[0]
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def _connection() -> sqlite3.Connection:
    STORE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STORE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT, endpoint TEXT, request_fingerprint TEXT,
            content_hash TEXT, fetched_at TEXT, resulted_in_new_snapshot INTEGER,
            schema_version TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_snapshot (
            sport TEXT, entity_id TEXT, endpoint TEXT, provider TEXT,
            fetched_at TEXT, content_hash TEXT, payload TEXT,
            schema_version TEXT, provider_entity_id TEXT,
            event_time TEXT, published_time TEXT,
            available_to_model_time TEXT, ingested_at TEXT,
            PRIMARY KEY (sport, entity_id, endpoint, provider, fetched_at)
        )
    """)
    _migrate_columns(conn)
    return conn


def _content_hash(payload: dict, schema_version: str) -> str:
    """Hash du payload ET du schema_version (GW-NFR-002) : un changement de schéma
    produit un hash différent, donc un nouveau snapshot, jamais une dédup trompeuse."""
    material = json.dumps(payload, sort_keys=True) + "|" + schema_version
    return hashlib.sha256(material.encode()).hexdigest()


def _last_content_hash(
    conn: sqlite3.Connection, sport: str, entity_id: str, endpoint: str, provider: str, schema_version: str
) -> str | None:
    row = conn.execute(
        "SELECT content_hash FROM data_snapshot "
        "WHERE sport=? AND entity_id=? AND endpoint=? AND provider=? AND schema_version=? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (sport, entity_id, endpoint, provider, schema_version),
    ).fetchone()
    return row[0] if row else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def write(
    sport: str,
    entity_id: str,
    endpoint: str,
    provider: str,
    payload: dict,
    request_fingerprint: str,
    fetched_at: datetime,
    schema_version: str,
    provider_entity_id: str | None = None,
    event_time: datetime | None = None,
    published_time: datetime | None = None,
    available_to_model_time: datetime | None = None,
    ingested_at: datetime | None = None,
) -> FetchEvent:
    """Trace l'appel (toujours), écrit le snapshot seulement si le contenu a changé.

    Les 5 horodatages sont persistés distinctement (ADR-004). event_time et
    published_time sont écrits tels quels — None explicite si le provider ne les
    fournit pas, jamais fabriqués. Par défaut available_to_model_time=fetched_at
    et ingested_at=maintenant si non fournis.
    """
    available_to_model_time = available_to_model_time or fetched_at
    ingested_at = ingested_at or datetime.now(timezone.utc)

    conn = _connection()
    try:
        content_hash = _content_hash(payload, schema_version)
        previous_hash = _last_content_hash(conn, sport, entity_id, endpoint, provider, schema_version)
        is_new = content_hash != previous_hash

        if is_new:
            conn.execute(
                "INSERT INTO data_snapshot "
                "(sport, entity_id, endpoint, provider, fetched_at, content_hash, payload, "
                " schema_version, provider_entity_id, event_time, published_time, "
                " available_to_model_time, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sport, entity_id, endpoint, provider, fetched_at.isoformat(), content_hash,
                    json.dumps(payload), schema_version, provider_entity_id,
                    _iso(event_time), _iso(published_time),
                    available_to_model_time.isoformat(), ingested_at.isoformat(),
                ),
            )
        conn.execute(
            "INSERT INTO fetch_event "
            "(provider, endpoint, request_fingerprint, content_hash, fetched_at, resulted_in_new_snapshot, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (provider, endpoint, request_fingerprint, content_hash, fetched_at.isoformat(), int(is_new), schema_version),
        )
        conn.commit()
        return FetchEvent(provider, endpoint, request_fingerprint, content_hash, fetched_at, is_new)
    finally:
        conn.close()


def last_snapshot(sport: str, entity_id: str, endpoint: str, provider: str | None = None) -> dict | None:
    """Dernier snapshot connu — recours final du fallback_chain quand tous les providers échouent.

    Retourne aussi schema_version : l'appelant DOIT vérifier la compatibilité de
    schéma (is_schema_compatible) avant de servir la donnée (GW-FR-009).
    """
    conn = _connection()
    try:
        cols = "payload, fetched_at, provider, schema_version, provider_entity_id, " \
               "event_time, published_time, available_to_model_time, ingested_at"
        if provider:
            query = (
                f"SELECT {cols} FROM data_snapshot "
                "WHERE sport=? AND entity_id=? AND endpoint=? AND provider=? ORDER BY fetched_at DESC LIMIT 1"
            )
            params = (sport, entity_id, endpoint, provider)
        else:
            query = (
                f"SELECT {cols} FROM data_snapshot "
                "WHERE sport=? AND entity_id=? AND endpoint=? ORDER BY fetched_at DESC LIMIT 1"
            )
            params = (sport, entity_id, endpoint)
        row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        return {
            "payload": json.loads(row[0]),
            "fetched_at": row[1],
            "provider": row[2],
            "schema_version": row[3],
            "provider_entity_id": row[4],
            "event_time": row[5],
            "published_time": row[6],
            "available_to_model_time": row[7],
            "ingested_at": row[8],
        }
    finally:
        conn.close()
