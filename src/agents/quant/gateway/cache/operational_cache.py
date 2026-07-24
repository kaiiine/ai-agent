"""Cache opérationnel devant les providers — accélère et déduplique, ne fournit jamais de donnée.

Politique indépendante du point_in_time_store : purger ce cache n'efface
jamais l'historique persistant (voir core/point_in_time_store.py).
"""

from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path

CACHE_DB = Path.home() / ".axon" / "sports_operational_cache.db"

TTL_SECONDS: dict[str, int] = {
    "fixtures": 24 * 3600,
    "standings": 6 * 3600,
    "injuries": 3600,
}
DEFAULT_TTL_SECONDS = 3600


def _connection() -> sqlite3.Connection:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, endpoint TEXT, ts REAL)")
    return conn


def cache_get(key: str, endpoint: str) -> dict | list | None:
    conn = _connection()
    try:
        row = conn.execute("SELECT value, ts FROM cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        ttl = TTL_SECONDS.get(endpoint, DEFAULT_TTL_SECONDS)
        if (time.time() - row[1]) >= ttl:
            return None
        return json.loads(row[0])
    finally:
        conn.close()


def cache_set(key: str, endpoint: str, value: dict | list) -> None:
    conn = _connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, endpoint, ts) VALUES (?, ?, ?, ?)",
            (key, json.dumps(value), endpoint, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def purge_expired() -> int:
    """Purge indépendante du point_in_time_store — n'affecte jamais l'historique persistant."""
    conn = _connection()
    try:
        rows = conn.execute("SELECT key, endpoint, ts FROM cache").fetchall()
        now = time.time()
        expired = [key for key, endpoint, ts in rows if (now - ts) >= TTL_SECONDS.get(endpoint, DEFAULT_TTL_SECONDS)]
        conn.executemany("DELETE FROM cache WHERE key = ?", [(k,) for k in expired])
        conn.commit()
        return len(expired)
    finally:
        conn.close()
