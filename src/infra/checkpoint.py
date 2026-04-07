# src/infra/checkpoint.py
"""
Checkpointer SQLite persistant pour LangGraph.

- Stocke les threads dans ~/.axon/memory.db
- Mémorise le dernier thread actif dans ~/.axon/last_thread
- Expose des helpers pour lister les threads et lire les derniers messages
  via l'API publique LangGraph (pas de parsing interne de blobs)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

# ── Répertoire de données Axon ─────────────────────────────────────────────────
_AXON_DIR = Path.home() / ".axon"
_DB_PATH   = _AXON_DIR / "memory.db"
_LAST_FILE = _AXON_DIR / "last_thread"

_AXON_DIR.mkdir(parents=True, exist_ok=True)

# Connexion SQLite partagée (check_same_thread=False requis par LangGraph)
_conn        = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
_checkpointer = SqliteSaver(_conn)


# ── Checkpointer ───────────────────────────────────────────────────────────────

def build_checkpointer() -> SqliteSaver:
    return _checkpointer


# ── Persistance du thread actif ────────────────────────────────────────────────

def save_last_thread(thread_id: str) -> None:
    _LAST_FILE.write_text(thread_id, encoding="utf-8")


def load_last_thread() -> Optional[str]:
    if _LAST_FILE.exists():
        tid = _LAST_FILE.read_text(encoding="utf-8").strip()
        return tid or None
    return None


# ── Listing des threads ────────────────────────────────────────────────────────

def list_threads() -> list[dict]:
    """
    Retourne la liste des threads enregistrés, triés du plus récent au plus ancien.

    Chaque entrée : {thread_id, updated_at, created_at, preview}

    On interroge SQLite uniquement pour les métadonnées (thread_id + timestamps).
    Le preview est extrait via l'API publique LangGraph pour ne pas dépendre
    du format interne de sérialisation des blobs.
    """
    if not _DB_PATH.exists():
        return []

    try:
        cur = _conn.cursor()
        cur.execute("""
            SELECT
                thread_id,
                MIN(checkpoint_id) AS created_id,
                MAX(checkpoint_id) AS updated_id
            FROM checkpoints
            GROUP BY thread_id
            ORDER BY updated_id DESC
        """)
        rows = cur.fetchall()
    except Exception:
        return []

    threads = []
    for (thread_id, _, _) in rows:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            tup = _checkpointer.get_tuple(config)
        except Exception:
            tup = None

        updated_at = ""
        preview    = ""

        if tup:
            # Timestamp ISO du checkpoint
            ts = tup.checkpoint.get("ts", "")
            updated_at = _fmt_ts(ts)
            # Preview = dernier message humain
            msgs = tup.checkpoint.get("channel_values", {}).get("messages", [])
            preview = _last_human_preview(msgs)

        threads.append({
            "thread_id":  thread_id,
            "updated_at": updated_at,
            "preview":    preview,
        })

    return threads


def get_recent_messages(thread_id: str, n: int = 6) -> list[dict]:
    """
    Retourne les N derniers messages d'un thread sous forme de dicts simples
    {role, content} en utilisant l'API publique LangGraph.
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        tup = _checkpointer.get_tuple(config)
    except Exception:
        return []

    if not tup:
        return []

    msgs: list[BaseMessage] = (
        tup.checkpoint.get("channel_values", {}).get("messages", [])
    )
    recent = msgs[-n:] if len(msgs) > n else msgs

    result = []
    for m in recent:
        role    = _role_of(m)
        content = _text_of(m)
        if content:
            result.append({"role": role, "content": content[:300]})
    return result


# ── Helpers internes ───────────────────────────────────────────────────────────

def _role_of(m: BaseMessage) -> str:
    if isinstance(m, HumanMessage):
        return "human"
    if isinstance(m, AIMessage):
        return "ai"
    return getattr(m, "type", "?")


def _text_of(m: BaseMessage) -> str:
    content = getattr(m, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        # Contenu multimodal — premier bloc texte
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "").strip()
    return ""


def _last_human_preview(msgs: list) -> str:
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            text = _text_of(m).replace("\n", " ")
            return text[:80] + ("…" if len(text) > 80 else "")
    return ""


def _fmt_ts(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return ts[:16]
