# src/orchestrator/invocation.py
"""Appeler le LLM, et survivre à ses échecs.

Une seule question : cet appel a échoué, que fait-on ? Quatre réponses possibles,
de la moins à la plus dégradée — réessayer, changer de clé (jamais de
fournisseur : le backend choisi fait foi),
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
from src.infra import trace

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
    # PANNES SERVEUR. Un 500/502/503 n'est ni un rate-limit, ni un contexte trop
    # long, ni une requête invalide : le serveur a échoué APRÈS avoir accepté.
    # Rien n'a été livré, aucun outil n'a pu s'exécuter — réémettre est aussi sûr
    # qu'après une coupure de flux, et c'est le seul remède qui ait du sens.
    #
    # Vécu : « erreur : Internal Server Error (ref: …) (status code: -1) » a tué
    # un tour en plein milieu d'un nettoyage disque. La classe `unknown` s'en
    # chargeait, mais avec le mauvais traitement — elle fait tourner les clés
    # puis retire les outils, ce qui ne répare pas une panne serveur et dégrade
    # le tour pour rien.
    "internal server error",
    "500 server error",
    "502",
    "bad gateway",
    "503",
    "service unavailable",
    "504",
    "gateway timeout",
    "overloaded",
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
        if not key:
            # JAMAIS de clé vide quand des clés sont configurées. Un client sans
            # clé n'échoue pas : chez Ollama il s'authentifie avec l'identité
            # machine `~/.ollama/id_ed25519`, donc sur un compte qui n'est pas
            # celui qu'on croit et dont personne ne surveille le quota. Toutes
            # les clés « en cooldown » valent mieux que ça : un cooldown est une
            # mémoire locale de quelques dizaines de minutes, pas une preuve.
            _configurees = get_pool().keys_for(backend) or []
            key = _configurees[0] if _configurees else ""
    except Exception:
        key = ""

    transient_retries = 0
    capped = compressed = degraded = stripped_tools = False
    removals: list = []
    summary = None
    origine = list(working)

    #: Clés déjà tentées DANS CET APPEL — borne la rotation sans dépendre du
    #: cooldown, qui peut être obsolète.
    _essayees: set[str] = set()

    def _rebind(nouveau_llm):
        return nouveau_llm if force_text else nouveau_llm.bind_tools(selected_tools)

    def _basculer() -> bool:
        """Passe à la clé suivante DU MÊME fournisseur. `False` si aucune n'est libre.

        LE BACKEND CHOISI FAIT FOI. Cette fonction changeait auparavant de
        FOURNISSEUR — et réécrivait `settings.llm_backend` au passage. Deux
        conséquences vécues : le modèle qui répondait n'était plus celui demandé
        (une question posée à `ollama_cloud` recevait une réponse de Gemini,
        sans que rien ne le signale), et `/config` affichait un backend que
        l'utilisateur n'avait pas choisi.

        Avoir plusieurs clés sert à traverser un quota, pas à changer de modèle.
        Quand toutes les clés du fournisseur sont épuisées, on le dit et on
        s'arrête : c'est à l'utilisateur d'arbitrer avec `/backend`.
        """
        nonlocal key, llm
        try:
            from src.llm.key_pool import get_pool
            pool = get_pool()
            pool.mark_rate_limited(provider, key)
            _essayees.add(key)
            suivante = pool.next_healthy(provider)
            if suivante in _essayees:
                suivante = ""
            if not suivante:
                # Aucune clé « saine », mais le cooldown se compte en dizaines de
                # minutes et se déclenche aussi sur une panne passagère. Avant de
                # renoncer, on essaie celles qu'on n'a PAS ENCORE tentées dans cet
                # appel — mesuré : deux clés parfaitement valides restaient
                # inutilisées parce qu'un incident les avait toutes marquées.
                suivante = next((k for k in (pool.keys_for(provider) or [])
                                 if k not in _essayees), "")
            if not suivante:
                return False
            key = suivante
            llm = _rebind(make_orchestrator_llm_with_key(provider, key))
            return True
        except Exception:
            return False

    depart = time.monotonic()

    while True:
        try:
            response = llm.invoke(working)
            usage = getattr(response, "usage_metadata", None)
            if usage:
                from src.ui.token_gauge import update_usage
                update_usage(usage)
            # Les tokens passaient déjà ICI, et n'allaient qu'à une jauge
            # d'écran : mesurés à chaque tour, puis morts avec l'affichage. Le
            # plancher de schémas qui dépassait Groq — 30 outils, 12 731 tokens —
            # était donc mesurable en continu depuis le début, et a pourtant
            # demandé une mesure manuelle.
            trace.inscrire(trace.Action(
                genre=trace.APPEL_LLM,
                resultat=trace.OK,
                backend=backend,
                modele=str(getattr(llm, "model", "") or getattr(llm, "model_name", "")),
                tokens_entree=int((usage or {}).get("input_tokens") or 0),
                tokens_sortie=int((usage or {}).get("output_tokens") or 0),
                latence_ms=int((time.monotonic() - depart) * 1000),
                # Ce que l'appel a coûté en stratégies. Une réponse obtenue au
                # quatrième essai n'est pas la même qu'une réponse du premier, et
                # `failure_log` compte les échecs sans dire comment ça a fini.
                extra={k: v for k, v in (
                    ("retries", transient_retries), ("capped", capped),
                    ("compressed", compressed), ("degraded", degraded),
                    ("sans_outils", stripped_tools)) if v},
            ))
            return Outcome(response=response, working=working,
                           removals=removals, summary=summary)

        except Exception as exc:
            genre = classify(exc)

            if genre == "transient":
                transient_retries += 1
                if transient_retries > MAX_TRANSIENT_RETRIES:
                    # On renonce ICI, volontairement. Basculer sur l'échelle
                    # dégradée retirerait les outils — et répondre SANS outils à
                    # « supprime ces fichiers » produit un texte plausible au
                    # lieu d'une action. Face à un réseau qui reste coupé, une
                    # erreur franche vaut mieux qu'une réponse qui fait semblant.
                    _log_failure(provider, exc, "retry", False)
                    raise
                notify(f"panne passagère — reprise {transient_retries}/{MAX_TRANSIENT_RETRIES}…")
                sleep(2 ** (transient_retries - 1))
                _log_failure(provider, exc, "retry", True)
                continue

            if genre == "rate_limit":
                precedent = provider
                if _basculer():
                    notify(f"quota atteint sur {provider} — clé suivante…")
                    _log_failure(precedent, exc, "key_rotate", True)
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
                        notify(f"{provider} a échoué ({type(exc).__name__}) — "
                               f"clé suivante…")
                        _log_failure(precedent, exc, "key_rotate", True)
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
