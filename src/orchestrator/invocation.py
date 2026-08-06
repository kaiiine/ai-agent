# src/orchestrator/invocation.py
"""Appeler le LLM, et survivre à ses échecs.

Une seule question : cet appel a échoué, que fait-on ? Quatre réponses possibles,
de la moins à la plus dégradée — réessayer, changer de clé ou de provider,
réduire le contexte, renoncer aux outils. L'ordre compte : appliquer une
stratégie coûteuse à une panne bénigne fait perdre plus que l'incident.

Séparé de `graph.py` parce que la question est autonome. Elle ne dépend d'aucun
état du graphe : tout ce qu'il faut arrive en paramètre, et tout ce qui a bougé
repart dans `Outcome`. C'est ce qui rend chaque stratégie testable avec un faux
LLM qui lève l'erreur voulue, plutôt qu'en cherchant des chaînes dans le source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.messages import SystemMessage

from src.orchestrator.context import (
    _SUMMARY_MARKER,
    _cap_tool_messages,
    _compress_context,
    _drop_smartest,
    _estimate_tokens,
)
from src.orchestrator.resilience import _log_failure

RATE_LIMIT_MARKERS = (
    "429",
    "too many requests",
    "resource_exhausted",
    "resource has been exhausted",   # même chose en toutes lettres, sans code 429
    "rate limit",
    "quota exceeded",
    "session usage limit",
)

# Coupures de FLUX : la connexion tombe en cours de lecture, sans que la requête
# soit invalide. Ni un rate-limit, ni un dépassement de contexte — les deux
# seules classes autrefois traitées — donc l'erreur remontait telle quelle et le
# tour entier était perdu, réponse comprise. Réémettre est sûr : rien n'a été
# livré, aucun outil n'a pu s'exécuter.
TRANSIENT_MARKERS = (
    "incompleteread",
    "chunkedencoding",
    "protocolerror",
    "connection reset",
    "connection aborted",
    "remotedisconnected",
    "server disconnected",
    "read timed out",
    "readtimeout",
    "timed out",
    "econnreset",
)

MAX_TRANSIENT_RETRIES = 3

# Un dépassement de contexte se reconnaît au vocabulaire du provider, faute de
# code d'erreur commun.
_CONTEXT_MARKERS = ("context", "length", "token")


@dataclass
class Outcome:
    """Ce que l'appel a produit ET ce qu'il a modifié en chemin.

    `working` peut différer des messages d'entrée : une compression ou un
    tronquage réécrit la conversation. Les renvoyer explicitement évite que
    l'appelant continue sur une liste devenue obsolète."""
    response: Any
    working: list
    removals: list = field(default_factory=list)
    summary: Any | None = None


def classify(exc: Exception) -> str:
    """`transient` | `rate_limit` | `context` | `unknown`.

    Le nom de la CLASSE compte autant que le message : `IncompleteRead` n'apparaît
    que dans le type — `str(e)` seul donne « (66316 bytes read, 256871 more
    expected) », sans de quoi le reconnaître."""
    err = f"{type(exc).__name__}: {exc}".lower()
    if any(m in err for m in TRANSIENT_MARKERS):
        return "transient"
    if any(m in err for m in RATE_LIMIT_MARKERS):
        return "rate_limit"
    if any(m in err for m in _CONTEXT_MARKERS):
        return "context"
    return "unknown"


def invoke_with_recovery(
    llm,
    working: list,
    *,
    backend: str,
    factory: Callable[[], Any],
    selected_tools: list,
    force_text: bool,
    on_compress: Callable[[], None],
    notify: Callable[[str], None] = lambda _msg: None,
    sleep: Callable[[float], None] = time.sleep,
) -> Outcome:
    """Invoque `llm`, en appliquant les stratégies de récupération dans l'ordre.

    `sleep` et `notify` sont injectés pour que les tests n'attendent pas
    réellement et puissent observer ce qui a été tenté.
    """
    from src.infra.settings import settings
    from src.llm.models import make_orchestrator_llm_with_key

    provider = backend
    try:
        from src.llm.key_pool import get_pool
        key = get_pool().next_healthy(backend) or ""
    except Exception:
        key = ""

    transient_retries = 0
    capped = compressed = degraded = stripped_tools = False
    removals: list = []
    summary = None
    origine = list(working)

    def _rebind(nouveau_llm):
        return nouveau_llm if force_text else nouveau_llm.bind_tools(selected_tools)

    def _basculer() -> bool:
        """Passe à la clé ou au provider suivant. `False` si aucun n'est libre."""
        nonlocal provider, key, llm
        try:
            from src.llm.key_pool import get_fallback_order, get_pool, note_auto_fallback
            suivant = get_pool().next_provider_and_key(provider, key, get_fallback_order())
            if not suivant:
                return False
            precedent = provider
            provider, key = suivant
            settings.llm_backend = provider
            note_auto_fallback(precedent, provider)   # bascule réversible au tour suivant
            llm = _rebind(make_orchestrator_llm_with_key(provider, key))
            return True
        except Exception:
            return False

    while True:
        try:
            response = llm.invoke(working)
            usage = getattr(response, "usage_metadata", None)
            if usage:
                from src.ui.token_gauge import update_usage
                update_usage(usage)
            return Outcome(response=response, working=working,
                           removals=removals, summary=summary)

        except Exception as exc:
            genre = classify(exc)

            if genre == "transient":
                transient_retries += 1
                if transient_retries > MAX_TRANSIENT_RETRIES:
                    _log_failure(provider, exc, "retry", False)
                    raise
                notify(f"flux interrompu — reprise {transient_retries}/{MAX_TRANSIENT_RETRIES}…")
                sleep(2 ** (transient_retries - 1))
                _log_failure(provider, exc, "retry", True)
                continue

            if genre == "rate_limit":
                precedent = provider
                if _basculer():
                    _log_failure(precedent, exc, "provider_switch", True)
                    continue
                _log_failure(provider, exc, "none", False)
                raise

            if genre == "unknown":
                # Presque toujours le provider — modèle retiré, schéma d'outil
                # refusé, réponse malformée. Basculer a de bonnes chances
                # d'aboutir ; à défaut, le modèle doit au moins pouvoir DIRE ce
                # qui s'est passé plutôt que de laisser une erreur nue.
                if not degraded:
                    degraded = True
                    precedent = provider
                    if _basculer():
                        notify(f"{precedent} a échoué ({type(exc).__name__}) — "
                               f"bascule sur {provider}…")
                        _log_failure(precedent, exc, "provider_switch", True)
                        continue

                if not stripped_tools and not force_text:
                    stripped_tools = True
                    notify("nouvel échec — dernière tentative sans outils…")
                    llm = factory()
                    _log_failure(provider, exc, "no_tools", True)
                    working = working + [SystemMessage(content=(
                        "Les appels d'outils viennent d'échouer "
                        f"({type(exc).__name__}: {str(exc)[:200]}). Réponds en texte : "
                        "explique brièvement que l'action n'a pas pu être exécutée et "
                        "pourquoi. N'invente aucun résultat."))]
                    continue

                _log_failure(provider, exc, "none", False)
                raise

            # genre == "context" : réduire, du moins au plus destructeur.
            if not capped:
                capped = True
                working = _cap_tool_messages(working)
                notify("contexte trop long — tronquage des résultats tools…")

            elif not compressed:
                compressed = True
                on_compress()
                avant = _estimate_tokens(origine)
                working, retires = _compress_context(working, factory(), backend)
                apres = _estimate_tokens(working)
                libere = avant - apres
                part = f" — {100 * libere / avant:.0f} %" if avant else ""
                notify(f"compression : {libere:,} tokens libérés{part} "
                       f"({avant:,} → {apres:,})".replace(",", " "))
                removals.extend(r for r in retires if r not in removals)
                summary = next(
                    (m for m in working
                     if isinstance(m, SystemMessage) and _SUMMARY_MARKER in str(m.content)),
                    summary,
                )

            else:
                reduit = _drop_smartest(working)
                if reduit is None or len(reduit) <= 1:
                    _log_failure(provider, exc, "none", False)
                    raise
                working = reduit
                notify(f"drop tool round ({len(working)} messages restants)…")
