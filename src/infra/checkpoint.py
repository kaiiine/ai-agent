# src/infra/checkpoint.py
"""
Checkpointer SQLite persistant pour LangGraph.

- Stocke les threads dans ~/.axon/memory.db
- Mémorise le dernier thread actif dans ~/.axon/last_thread
- Expose des helpers pour lister les threads et lire les derniers messages
  via l'API publique LangGraph (pas de parsing interne de blobs)
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage

# ── Répertoire de données Axon ─────────────────────────────────────────────────
# Déclaré dans `src/infra/chemins.py` : neuf fichiers recalculaient ce chemin, et
# aucun ne pouvait être déplacé.
from src.infra import chemins as _chemins

_AXON_DIR   = _chemins.racine_etat()
_DB_PATH    = _chemins.base_memoire()
_LAST_FILE  = _chemins.dernier_thread()
_CWD_FILE   = _AXON_DIR / "thread_cwds.json"

_AXON_DIR.mkdir(parents=True, exist_ok=True)

# Connexion SQLite partagée (check_same_thread=False requis par LangGraph)
_conn        = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
_checkpointer = SqliteSaver(_conn)


# ── Checkpointer ───────────────────────────────────────────────────────────────

def build_checkpointer() -> SqliteSaver:
    return _checkpointer


# ── Persistance du thread actif ────────────────────────────────────────────────

def _ecrire_atomique(chemin: Path, contenu: str) -> None:
    """Écrit via un fichier temporaire puis un rename, jamais en place.

    `write_text` tronque la cible AVANT d'écrire : un processus tué au mauvais
    moment laisse un fichier à moitié écrit. Pour `thread_cwds.json` ce n'est pas
    une gêne passagère mais une perte définitive, car la lecture suivante échoue
    et l'écriture d'après repart d'une table VIDE (cf. save_thread_cwd).

    `os.replace` est atomique sur le même système de fichiers : le fichier
    contient soit l'ancien état complet, soit le nouveau, jamais un moignon.
    """
    tmp = chemin.with_name(chemin.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(contenu)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, chemin)


def save_last_thread(thread_id: str) -> None:
    _ecrire_atomique(_LAST_FILE, thread_id)


def load_last_thread() -> Optional[str]:
    if _LAST_FILE.exists():
        tid = _LAST_FILE.read_text(encoding="utf-8").strip()
        return tid or None
    return None


# ── Persistance du cwd par thread ─────────────────────────────────────────────

def save_thread_cwd(thread_id: str, cwd: str) -> None:
    """Enregistre le répertoire de travail d'un thread.

    Le `except: pass` d'origine laissait `data` à {} quand le JSON était
    illisible, puis RÉÉCRIVAIT le fichier : une seule lecture ratée effaçait le
    cwd de tous les autres threads. Mesuré sur trois threads, il en restait un ;
    le fichier réel en contient 286.

    Les deux moitiés du défaut se nourrissaient l'une l'autre — l'écriture non
    atomique produisait précisément le JSON tronqué que la lecture suivante ne
    savait pas relire. Elles sont corrigées ensemble, et un fichier illisible est
    désormais mis de côté plutôt qu'écrasé : il reste récupérable à la main.
    """
    data: dict = {}
    if _CWD_FILE.exists():
        try:
            data = json.loads(_CWD_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("table de cwd corrompue")
        except Exception:
            data = {}
            horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                _CWD_FILE.rename(_CWD_FILE.with_name(f"{_CWD_FILE.name}.corrompu-{horodatage}"))
            except OSError:
                pass

    data[thread_id] = cwd
    # Écriture par lecture-modification-écriture : deux sessions AXON simultanées
    # peuvent encore se perdre mutuellement leur DERNIÈRE entrée. C'est une entrée,
    # pas la table entière, et poser un verrou coûterait plus que ce cas ne pèse.
    _ecrire_atomique(_CWD_FILE, json.dumps(data))


def load_thread_cwd(thread_id: str) -> Optional[str]:
    if not _CWD_FILE.exists():
        return None
    try:
        data = json.loads(_CWD_FILE.read_text(encoding="utf-8"))
        return data.get(thread_id)
    except Exception:
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


def get_recent_messages(thread_id: str, n: int | None = None) -> list[dict]:
    """
    Retourne les messages d'un thread sous forme de dicts {role, content}.
    n=None → tous les messages. n=K → les K derniers.
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
    if n is not None:
        msgs = msgs[-n:] if len(msgs) > n else msgs

    from src.orchestrator.note_interne import est_interne

    result = []
    for m in msgs:
        role    = _role_of(m)
        content = _text_of(m)
        if content:
            # `interne` : AXON se l'est écrit à lui-même (compte rendu de revue,
            # rapport d'un sous-agent, décision sur un plan). Le rôle reste
            # `human` — c'est bien une entrée pour le modèle — mais ce n'est pas
            # un tour de l'utilisateur, et le rejouer comme tel affichait la
            # plomberie à l'écran.
            result.append({"role": role, "content": content,
                           "interne": est_interne(m)})
    return result


# ── Helpers internes ───────────────────────────────────────────────────────────

def _role_of(m: BaseMessage) -> str:
    if isinstance(m, HumanMessage):
        return "human"
    if isinstance(m, AIMessage):
        return "ai"
    if isinstance(m, ToolMessage) and getattr(m, "name", "") == "run_coding_agent":
        return "coding_agent"
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
