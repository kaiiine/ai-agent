import os
from difflib import SequenceMatcher
from typing import Optional, Dict, Any
from langchain_core.tools import tool
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import emoji as emoji_lib

_USER_CACHE: Dict[str, str] = {}


def _resolve_user(client: WebClient, user_id: str) -> str:
    """Résout un user ID Slack en nom réel."""
    if not user_id:
        return "?"
    if user_id in _USER_CACHE:
        return _USER_CACHE[user_id]
    try:
        info = client.users_info(user=user_id)
        u = info["user"]
        name = u.get("real_name") or u.get("display_name") or u.get("name", user_id)
        _USER_CACHE[user_id] = name
        return name
    except Exception:
        return user_id


def _convert_emojis(text: str) -> str:
    """Convertit les emojis Slack :name: en Unicode."""
    return emoji_lib.emojize(text, language="alias")


def _client() -> WebClient:
    """Toutes les opérations passent par le user token."""
    token = os.getenv("SLACK_USER_TOKEN")
    if not token:
        raise RuntimeError("SLACK_USER_TOKEN manquant dans .env")
    return WebClient(token=token)


def _user_client() -> WebClient:
    return _client()


def _normalize(s: str) -> str:
    """Normalise une chaîne : minuscules, underscores → espaces, espaces multiples réduits."""
    return " ".join(s.lower().replace("_", " ").replace(".", " ").split())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _find_user_id_by_name(client: WebClient, name: str) -> str | None:
    """Cherche un user ID par nom approximatif (fuzzy, insensible à la casse et aux fautes légères)."""
    needle = _normalize(name)
    needle_parts = needle.split()
    best_id, best_score = None, 0.0
    for resp in client.users_list(limit=200):
        for u in resp.get("members", []):
            if u.get("deleted") or u.get("is_bot"):
                continue
            candidates = [
                _normalize(u.get("real_name", "")),
                _normalize(u.get("name", "")),
                _normalize(u.get("profile", {}).get("display_name", "")),
            ]
            for c in candidates:
                # Match exact partiel (prénom seul)
                if any(p in c for p in needle_parts):
                    score = max([_similarity(needle, c)] + [_similarity(needle, part) for part in c.split()])
                else:
                    score = _similarity(needle, c)
                if score > best_score:
                    best_score, best_id = score, u["id"]
    return best_id if best_score >= 0.6 else None


def _resolve_channel(client: WebClient, name_or_id: str) -> str:
    """Résout un nom de channel (#general), @nom ou ID (C/D/G...) → channel ID."""
    if name_or_id.startswith(("C", "D", "G", "W")):
        return name_or_id

    # @nom → DM avec cet utilisateur
    if name_or_id.startswith("@"):
        user_name = name_or_id.lstrip("@")
        user_id = _find_user_id_by_name(client, user_name)
        if not user_id:
            raise ValueError(f"Utilisateur introuvable : {name_or_id}")
        resp = client.conversations_open(users=user_id)
        return resp["channel"]["id"]

    # #channel ou nom brut → cherche dans les channels
    clean = name_or_id.lstrip("#")
    for types in ("public_channel,im,mpim", "private_channel"):
        try:
            for resp in client.conversations_list(types=types, limit=200):
                for ch in resp.get("channels", []):
                    if ch.get("name") == clean:
                        return ch["id"]
        except SlackApiError:
            pass

    # Dernier recours : interprète comme un nom de personne → DM
    user_id = _find_user_id_by_name(client, name_or_id)
    if user_id:
        resp = client.conversations_open(users=user_id)
        return resp["channel"]["id"]

    raise ValueError(f"Canal ou utilisateur introuvable : '{name_or_id}'")


@tool("slack_find_user")
def slack_find_user(name: str) -> Dict[str, Any]:
    """
    Recherche un utilisateur Slack par nom approximatif (prénom, nom, username).
    Retourne son vrai nom, son @handle et son ID pour pouvoir lui envoyer un DM.

    Args:
        name: nom approximatif (ex: "nicolas", "danquigny", "nicolas danquigny")
    Returns:
        {"status": "ok", "matches": [{"id", "real_name", "handle", "display_name"}, ...]}
    """
    client = _client()
    try:
        needle = _normalize(name)
        needle_parts = needle.split()
        matches = []
        for resp in client.users_list(limit=200):
            for u in resp.get("members", []):
                if u.get("deleted") or u.get("is_bot"):
                    continue
                candidates = [
                    _normalize(u.get("real_name", "")),
                    _normalize(u.get("name", "")),
                    _normalize(u.get("profile", {}).get("display_name", "")),
                ]
                if any(needle in c for c in candidates) or any(all(p in c for p in needle_parts) for c in candidates):
                    matches.append({
                        "id": u["id"],
                        "real_name": u.get("real_name", ""),
                        "handle": f"@{u.get('name', '')}",
                        "display_name": u.get("profile", {}).get("display_name", ""),
                    })
        if not matches:
            return {"status": "empty", "matches": []}
        return {"status": "ok", "count": len(matches), "matches": matches}
    except SlackApiError as e:
        return {"status": "error", "error": str(e)}


@tool("slack_list_channels")
def slack_list_channels(include_private: bool = True) -> Dict[str, Any]:
    """
    Liste les channels Slack disponibles (publics et privés).

    Args:
        include_private: inclure les channels privés (True par défaut)
    Returns:
        {"status": "ok", "channels": [{"id", "name", "is_private", "topic", "member_count"}, ...]}
    """
    client = _client()
    try:
        types = "public_channel,private_channel" if include_private else "public_channel"
        channels = []
        for resp in client.conversations_list(types=types, limit=200):
            for ch in resp.get("channels", []):
                channels.append({
                    "id": ch["id"],
                    "name": ch.get("name", ""),
                    "is_private": ch.get("is_private", False),
                    "topic": ch.get("topic", {}).get("value", ""),
                    "member_count": ch.get("num_members", 0),
                })
        return {"status": "ok", "count": len(channels), "channels": channels}
    except SlackApiError as e:
        return {"status": "error", "error": str(e)}


@tool("slack_read_channel")
def slack_read_channel(channel: str, limit: int = 20) -> Dict[str, Any]:
    """
    Lit les derniers messages d'un channel (public, privé) ou d'un DM.

    Args:
        channel: nom (#general) ou ID du channel/DM
        limit: nombre de messages à récupérer (max 100)
    Returns:
        {"status": "ok", "channel": "...", "messages": [{"user", "text", "ts", "reactions"}, ...]}
    """
    client = _client()
    try:
        channel_id = _resolve_channel(client, channel)
        resp = client.conversations_history(channel=channel_id, limit=min(limit, 100))
        messages = []
        for m in resp.get("messages", []):
            if m.get("subtype"):
                continue
            reactions = [
                {"emoji": emoji_lib.emojize(f':{r["name"]}:', language="alias"), "count": r["count"]}
                for r in m.get("reactions", [])
            ]
            raw_text = m.get("text", "")
            messages.append({
                "user": _resolve_user(client, m.get("user", m.get("username", ""))),
                "text": _convert_emojis(raw_text),
                "ts": m.get("ts"),
                "thread_replies": m.get("reply_count", 0),
                "reactions": reactions,
            })
        return {"status": "ok", "channel": channel, "messages": messages}
    except SlackApiError as e:
        return {"status": "error", "error": str(e)}


@tool("slack_get_mentions")
def slack_get_mentions(limit: int = 20) -> Dict[str, Any]:
    """
    Récupère les messages récents où l'utilisateur est mentionné (@mention).
    Nécessite SLACK_USER_TOKEN dans .env avec le scope search:read.

    Args:
        limit: nombre de résultats max (défaut 20)
    Returns:
        {"status": "ok", "mentions": [{"channel", "user", "text", "ts", "link"}, ...]}
    """
    try:
        user_id = os.getenv("SLACK_USER_ID", "")
        if not user_id:
            return {"status": "error", "error": "SLACK_USER_ID manquant dans .env"}
        client = _user_client()
        resp = client.search_messages(query=f"<@{user_id}>", count=min(limit, 50), sort="timestamp")
        matches = resp.get("messages", {}).get("matches", [])
        mentions = [
            {
                "channel": m.get("channel", {}).get("name", "?"),
                "user": m.get("username", "?"),
                "text": m.get("text", ""),
                "ts": m.get("ts"),
                "link": m.get("permalink", ""),
            }
            for m in matches
        ]
        return {"status": "ok", "count": len(mentions), "mentions": mentions}
    except SlackApiError as e:
        return {"status": "error", "error": str(e)}
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}


@tool("slack_list_dms")
def slack_list_dms() -> Dict[str, Any]:
    """
    Liste les conversations directes (DMs) actives.

    Returns:
        {"status": "ok", "dms": [{"id", "user_id", "name"}, ...]}
    """
    client = _client()
    try:
        dms = []
        for resp in client.conversations_list(types="im", limit=100):
            for ch in resp.get("channels", []):
                user_id = ch.get("user", "")
                name = "?"
                try:
                    info = client.users_info(user=user_id)
                    name = info["user"].get("real_name") or info["user"].get("name", user_id)
                except Exception:
                    name = user_id
                dms.append({"id": ch["id"], "user_id": user_id, "name": name})
        return {"status": "ok", "count": len(dms), "dms": dms}
    except SlackApiError as e:
        return {"status": "error", "error": str(e)}


@tool("slack_send_message")
def slack_send_message(
    channel: str,
    text: str,
    thread_ts: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Envoie un message dans un channel Slack ou en DM.
    Le message est envoyé tel quel — le LLM doit le rédiger proprement avant d'appeler ce tool.

    Args:
        channel: nom (#general, @username) ou ID du channel/DM
        text: contenu du message (markdown Slack supporté : *gras*, _italique_, `code`, ```bloc```)
        thread_ts: timestamp du message parent pour répondre dans un thread (optionnel)
    Returns:
        {"status": "ok", "ts": "...", "channel": "..."}
    """
    client = _client()
    try:
        channel_id = _resolve_channel(client, channel)
        kwargs: Dict[str, Any] = {"channel": channel_id, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        resp = client.chat_postMessage(**kwargs)
        return {
            "status": "ok",
            "ts": resp.get("ts"),
            "channel": resp.get("channel"),
            "message": "Message envoyé.",
        }
    except SlackApiError as e:
        return {"status": "error", "error": str(e)}


@tool("slack_search_messages")
def slack_search_messages(query: str, limit: int = 20) -> Dict[str, Any]:
    """
    Recherche dans tous les messages Slack (texte libre).
    Nécessite SLACK_USER_TOKEN dans .env avec le scope search:read.

    Args:
        query: texte à rechercher (supporte les opérateurs Slack: in:#channel, from:@user, before:YYYY-MM-DD)
        limit: nombre de résultats max (défaut 20)
    Returns:
        {"status": "ok", "results": [{"channel", "user", "text", "ts", "link"}, ...]}
    """
    try:
        client = _user_client()
        resp = client.search_messages(query=query, count=min(limit, 50), sort="timestamp")
        matches = resp.get("messages", {}).get("matches", [])
        results = [
            {
                "channel": m.get("channel", {}).get("name", "?"),
                "user": m.get("username", "?"),
                "text": m.get("text", ""),
                "ts": m.get("ts"),
                "link": m.get("permalink", ""),
            }
            for m in matches
        ]
        return {"status": "ok", "count": len(results), "results": results}
    except SlackApiError as e:
        return {"status": "error", "error": str(e)}
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}
