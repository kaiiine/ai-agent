"""Politique unique de rotation des clés et de bascule de fournisseur.

Elle a existé en deux exemplaires : ce module pour `/fiche`, `/exo` et `/letter`,
et quatre-vingt-dix lignes recopiées dans `specialist._run`. Même sémantique,
deux endroits à corriger — donc un endroit qu'on oubliait. Ce qui décide de ce
qu'est un 401, un quota, ou une panne serveur vit ici et nulle part ailleurs.

Le specialist consomme les primitives (il doit re-binder ses outils et mettre à
jour son budget de contexte entre deux clients) ; les chemins directs consomment
le générateur `clients`.
"""
from __future__ import annotations

import re
from typing import Callable, Iterator

#: Underscores et tirets : des séparateurs de mots, pas des caractères.
_SEPARATEURS = re.compile(r"[_\-]+")

# Une clé refusée est à écarter définitivement ; un quota se contente d'attendre.
# Ni 403 ni « forbidden » : c'est la réponse d'un modèle payant, pas d'une clé morte.
_CLE_MORTE = ("401", "unauthorized", "invalid api key", "invalid_api_key",
              "api key not valid")
_QUOTA = ("429", "too many requests", "rate limit", "quota exceeded",
          "resource exhausted",
          # Un quota par MINUTE, pas par requête. Groq le rend en 413 avec
          # « tokens per minute (TPM): Limit 8000, Requested 16927 » — aucun
          # « 429 » nulle part. Sans ces marqueurs il tombait dans `_CONTEXTE`,
          # parce que « token » figure dans « tokens per minute » : classé comme
          # une requête trop longue, donc jugé non réessayable, donc ni rotation
          # de clé ni repli de fournisseur. Le tour mourait sur un dump brut.
          "tokens per minute", "tpm", "per minute")
_CONTEXTE = ("context", "length", "token", "400", "exceed")
_SERVEUR = ("500", "502", "503", "504", "server error", "internal error",
            "bad gateway", "service unavailable")


def _normaliser(texte: str) -> str:
    """Minuscules, et séparateurs de mots unifiés.

    Les fournisseurs écrivent la même notion de trois façons : `rate_limit`,
    `rate limit`, `ratelimit`. Maintenir les trois variantes dans chaque table
    est une dette qui se paie au premier fournisseur qui en choisit une
    quatrième — et elle s'est payée : `rate_limit_exceeded` de Groq ne matchait
    ni « rate limit » ni « ratelimit », l'underscore tombant entre les deux.

    Normaliser des DEUX côtés fait disparaître la distinction une bonne fois.
    """
    return _SEPARATEURS.sub(" ", texte.lower())


def classer_erreur(exc: Exception) -> str:
    """« cle_morte » · « quota » · « contexte » · « serveur » · « autre ».

    L'ordre compte deux fois :
      - « 400 » figure parmi les marqueurs de contexte et happerait un 401 si la
        clé morte n'était pas testée d'abord ;
      - « token » y figure aussi, et happerait un quota par minute si le quota
        n'était pas testé avant.
    """
    message = _normaliser(str(exc))
    for marqueurs, nom in ((_CLE_MORTE, "cle_morte"), (_QUOTA, "quota"),
                           (_CONTEXTE, "contexte"), (_SERVEUR, "serveur")):
        if any(_normaliser(m) in message for m in marqueurs):
            return nom
    return "autre"


def vaut_la_peine_de_reessayer(exc: Exception) -> bool:
    """Cette erreur peut-elle se résoudre avec une autre clé ?"""
    return classer_erreur(exc) in ("cle_morte", "quota")


def marquer_echec(fournisseur: str, cle: str, exc: Exception) -> None:
    """Consigne l'échec pour que les autres chemins n'y retournent pas."""
    from src.llm.key_pool import get_pool

    try:
        pool = get_pool()
        if classer_erreur(exc) == "cle_morte":
            pool.mark_bad_key(fournisseur, cle)
        else:
            pool.mark_rate_limited(fournisseur, cle)
    except Exception:   # noqa: BLE001 — un échec de comptabilité ne casse rien
        pass


def cle_suivante(fournisseur: str, exclues: set[str]) -> str:
    """Prochaine clé utilisable de ce fournisseur, hors celles déjà essayées.

    On demande d'abord une clé saine, puis on se rabat sur n'importe quelle clé
    configurée : le pool peut avoir tout mis en cooldown alors qu'un quota s'est
    renouvelé entre-temps.
    """
    from src.llm.key_pool import get_pool

    pool = get_pool()
    candidate = pool.next_healthy(fournisseur)
    if candidate and candidate not in exclues:
        return candidate
    return next((k for k in (pool.keys_for(fournisseur) or []) if k not in exclues), "")


def fournisseur_suivant(exclus: set[str]) -> tuple[str, str] | None:
    """Prochain fournisseur ayant une clé SAINE, avec cette clé. None si aucun.

    Clé saine exigée, et pas seulement configurée : c'est nous qui venons de
    marquer les mortes, y retourner ferait boucler la bascule.
    """
    from src.llm.key_pool import get_fallback_order, get_pool

    pool = get_pool()
    for candidat in get_fallback_order():
        if candidat in exclus:
            continue
        cle = pool.next_healthy(candidat)
        if cle:
            return candidat, cle
    return None


def clients(backend: str, fabrique: Callable[[str, str], object],
            *, notifier: Callable[[str, str], None] | None = None
            ) -> Iterator[tuple[str, str, object]]:
    """Rend (fournisseur, clé, client) pour chaque clé du backend, puis des replis.

    `fabrique(fournisseur, cle)` construit le client. `notifier(fournisseur, cle)`
    est appelé à chaque changement, pour que l'utilisateur voie ce qui se passe.
    Le fournisseur et la clé sont rendus avec le client : sans eux, l'appelant ne
    saurait pas laquelle marquer en échec.
    """
    from src.llm.key_pool import get_fallback_order, get_pool

    pool = get_pool()
    ordre = [backend] + [p for p in get_fallback_order() if p != backend]
    premier = True
    for fournisseur in ordre:
        for cle in pool.keys_for(fournisseur) or []:
            if notifier and not premier:
                notifier(fournisseur, cle)
            premier = False
            yield fournisseur, cle, fabrique(fournisseur, cle)
