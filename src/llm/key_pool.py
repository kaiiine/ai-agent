"""
key_pool.py — Pool de clés API multi-comptes avec rotation automatique et cooldown.

Permet de gérer plusieurs clés par provider (ex : 5 comptes ollama_cloud) :
- round-robin entre les clés saines
- sur 429 : marque la clé en cooldown 1h, essaie la suivante
- sur épuisement quotidien : cooldown jusqu'à minuit UTC
- si toutes les clés d'un provider sont épuisées : bascule sur le provider suivant

.env :
    OLLAMA_CLOUD_API_KEYS=key1,key2,key3,key4,key5
    GEMINI_API_KEYS=key1,key2
    MISTRAL_API_KEYS=key1
    GROQ_API_KEYS=key1
    FALLBACK_ORDER=ollama_cloud,gemini,mistral
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

_STATE_FILE = Path.home() / ".axon" / "key_pool_state.json"
_DEFAULT_FALLBACK_ORDER = ["ollama_cloud", "gemini", "mistral"]

COOLDOWN_RATE_LIMIT = 3600        # 1h — RPM/RPD hit
COOLDOWN_BAD_KEY    = 7 * 86400   # 7j — clé invalide


def _parse_csv(value: str) -> list[str]:
    return [k.strip() for k in (value or "").split(",") if k.strip()]


class KeyPool:
    """
    Gère les clés API par provider avec cooldown persisté dans ~/.axon/key_pool_state.json.
    Thread-safe en lecture, atomique en écriture (même process).
    """

    def __init__(self) -> None:
        # provider → {key → expires_timestamp}
        self._exhausted: dict[str, dict[str, float]] = {}
        self._load()

    # ── lecture des clés configurées ────────────────────────────────────────

    def keys_for(self, provider: str) -> list[str]:
        """Retourne toutes les clés configurées pour un provider (dans l'ordre de priorité)."""
        from src.infra.settings import settings

        if provider == "ollama_cloud":
            keys = _parse_csv(getattr(settings, "ollama_cloud_api_keys", ""))
            single = settings.ollama_api_key
        elif provider == "gemini":
            keys = _parse_csv(getattr(settings, "gemini_api_keys", ""))
            single = settings.gemini_api_key
        elif provider == "mistral":
            keys = _parse_csv(getattr(settings, "mistral_api_keys", ""))
            single = settings.mistral_api_key
        elif provider == "groq":
            keys = _parse_csv(getattr(settings, "groq_api_keys", ""))
            single = settings.groq_api_key
        else:
            return []

        # Ajoute la clé unique en première position si elle n'est pas déjà dans la liste
        if single and single not in keys:
            keys.insert(0, single)
        return keys

    # ── sélection de la prochaine clé saine ─────────────────────────────────

    def next_healthy(self, provider: str) -> Optional[str]:
        """Retourne la première clé saine pour un provider, ou None si toutes épuisées."""
        now = time.time()
        exhausted = self._exhausted.get(provider, {})
        for key in self.keys_for(provider):
            if now >= exhausted.get(key, 0):
                return key
        return None

    def all_healthy(self, provider: str) -> list[str]:
        """Retourne toutes les clés saines pour un provider."""
        now = time.time()
        exhausted = self._exhausted.get(provider, {})
        return [k for k in self.keys_for(provider) if now >= exhausted.get(k, 0)]

    # ── logique de bascule ───────────────────────────────────────────────────

    def next_provider_and_key(
        self,
        current_provider: str,
        current_key: str,
        fallback_order: list[str],
    ) -> Optional[tuple[str, str]]:
        """
        Marque current_key comme rate-limitée, puis retourne le prochain (provider, clé)
        disponible selon fallback_order. Retourne None si tout est épuisé.
        """
        # Marque la clé courante en cooldown
        if current_key:
            self.mark_rate_limited(current_provider, current_key)

        # Essaie une autre clé du même provider en premier
        key = self.next_healthy(current_provider)
        if key:
            return (current_provider, key)

        # Puis les autres providers PAR ORDRE DE PRIORITÉ (pas seulement « après »
        # le provider courant) : si on est tombé sur un provider de secours et que le
        # provider préféré a de nouveau une clé saine, on doit pouvoir y revenir.
        # Le cooldown des clés empêche tout ping-pong (une clé qui vient d'échouer
        # n'est pas saine).
        for provider in fallback_order:
            if provider == current_provider:
                continue
            key = self.next_healthy(provider)
            if key:
                return (provider, key)

        return None  # tout épuisé

    # ── marquage des erreurs ─────────────────────────────────────────────────

    def mark_rate_limited(self, provider: str, key: str, duration: int = COOLDOWN_RATE_LIMIT) -> None:
        """Marque une clé en cooldown (défaut 1h)."""
        self._set(provider, key, time.time() + duration)

    def mark_daily_exhausted(self, provider: str, key: str) -> None:
        """Marque une clé épuisée jusqu'à minuit UTC."""
        import datetime
        tomorrow = (
            datetime.datetime.utcnow()
            .replace(hour=0, minute=0, second=0, microsecond=0)
        ) + datetime.timedelta(days=1)
        self._set(provider, key, tomorrow.timestamp())

    def mark_bad_key(self, provider: str, key: str) -> None:
        """Marque une clé comme invalide (7 jours)."""
        self._set(provider, key, time.time() + COOLDOWN_BAD_KEY)

    def reset_all(self) -> None:
        """Remet toutes les clés à l'état sain (reset manuel)."""
        self._exhausted = {}
        self._save()

    def reset_provider(self, provider: str) -> None:
        """Remet les clés d'un provider à l'état sain."""
        self._exhausted.pop(provider, None)
        self._save()

    # ── status pour /keys ────────────────────────────────────────────────────

    def status(self, providers: Optional[list[str]] = None) -> list[dict]:
        """Retourne l'état de toutes les clés configurées."""
        now = time.time()
        rows: list[dict] = []
        for provider in (providers or _DEFAULT_FALLBACK_ORDER):
            keys = self.keys_for(provider)
            if not keys:
                continue
            exhausted = self._exhausted.get(provider, {})
            for key in keys:
                expires = exhausted.get(key, 0)
                healthy = now >= expires
                rows.append({
                    "provider": provider,
                    "key_short": key[:10] + "..." if len(key) > 13 else key,
                    "healthy": healthy,
                    "cooldown_left": max(0, int(expires - now)) if not healthy else 0,
                })
        return rows

    # ── persistance ──────────────────────────────────────────────────────────

    def _set(self, provider: str, key: str, expires: float) -> None:
        self._exhausted.setdefault(provider, {})[key] = expires
        self._save()

    def _load(self) -> None:
        try:
            self._exhausted = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            self._exhausted = {}

    def _save(self) -> None:
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = _STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._exhausted, indent=2), encoding="utf-8")
            tmp.replace(_STATE_FILE)
        except Exception:
            pass


# Singleton — importé partout via get_pool()
_pool = KeyPool()


def get_pool() -> KeyPool:
    return _pool


# ── Bascule AUTOMATIQUE de provider : temporaire, jamais définitive ──────────────
# Une bascule déclenchée par un rate-limit écrivait `settings.llm_backend` de façon
# PERMANENTE : une fois passé sur un provider de secours, toute la session y restait,
# même après l'expiration du cooldown et alors que le provider préféré avait de nouveau
# des clés saines (symptôme : « mes clés ollama sont dispo mais tout part sur gemini »).
# On mémorise donc l'origine de la bascule pour pouvoir revenir au provider préféré.
# Un changement VOLONTAIRE de backend (commande /backend) ne passe pas par ici et n'est
# donc jamais écrasé.
_auto_fallback: dict[str, str | None] = {"origin": None, "current": None}


def note_auto_fallback(origin: str, fallback: str) -> None:
    """Enregistre une bascule AUTOMATIQUE `origin` -> `fallback` (donc réversible)."""
    if origin and fallback and origin != fallback:
        if _auto_fallback["origin"] is None:
            _auto_fallback["origin"] = origin
        _auto_fallback["current"] = fallback


def clear_auto_fallback() -> None:
    _auto_fallback["origin"] = None
    _auto_fallback["current"] = None


def restore_preferred_backend(settings) -> str | None:
    """Revient au provider préféré si la bascule était automatique ET qu'il a de nouveau
    une clé saine. Retourne le provider restauré, sinon None.

    À appeler au DÉBUT de chaque tour : la bascule ne dure ainsi que le temps du cooldown.
    """
    origin = _auto_fallback["origin"]
    if not origin:
        return None
    if getattr(settings, "llm_backend", None) != _auto_fallback["current"]:
        clear_auto_fallback()      # l'utilisateur a changé de backend entre-temps
        return None
    if _pool.next_healthy(origin):
        settings.llm_backend = origin
        clear_auto_fallback()
        return origin
    return None


def get_fallback_order() -> list[str]:
    """Retourne l'ordre de fallback configuré (FALLBACK_ORDER env ou défaut)."""
    try:
        from src.infra.settings import settings
        raw = getattr(settings, "fallback_order", "")
        order = _parse_csv(raw)
        return order if order else _DEFAULT_FALLBACK_ORDER
    except Exception:
        return _DEFAULT_FALLBACK_ORDER
