"""Couche d'enrichissement Internet — ciblée, mise en cache, jamais quantitative.

Elle ne s'exécute PAS systématiquement. Un scan multisport voit des centaines de
rencontres ; lancer une recherche web sur chacune coûterait un quota entier pour
produire du bruit sur des événements qui n'ont besoin de rien.

Elle se déclenche donc sur un BLOCAGE identifié — ce sont les seuls cas où une
information externe peut expliquer quelque chose que le pipeline n'a pas su
résoudre seul. Et elle produit des `InternetFeature`, c'est-à-dire des faits
datés et sourcés, jamais un nombre qui entrerait dans un calcul.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Sequence

from .features import InternetFeature, make
from .sources import confidence_for, official_domains, sort_by_authority

#: Blocages pour lesquels une recherche externe a une chance d'expliquer quelque
#: chose. Un `EVENT_NOT_RESOLVED` sur un sport non enregistré, par exemple, n'a
#: rien à gagner d'une recherche web : c'est notre référentiel qui manque.
DECLENCHEURS = frozenset({
    "INSUFFICIENT_FEATURES",
    "PLAYER_IDENTITY_UNRESOLVED",
    "COMPETITION_NOT_RESOLVED",
    "PROVIDER_COVERAGE_MISSING",
    "COMPETITION_NOT_COVERED",
    "FRESHNESS_UNKNOWN",
    "DATA_TOO_STALE",
})

#: Portée d'une requête. Elle décide de la clé de cache, et c'est tout l'enjeu :
#: le tableau et la surface d'un tournoi sont les MÊMES pour ses trois rencontres.
#: Cachés par sujet, ils étaient re-cherchés une fois par rencontre — trois appels
#: réseau pour trois fois la même réponse.
EVENEMENT = "EVENEMENT"
COMPETITION = "COMPETITION"

#: Requêtes CIBLÉES par sport. Jamais « actualités tennis » : une recherche
#: générique rend des articles d'opinion, et c'est exactement ce qu'on ne veut
#: pas voir remonter comme « information ».
_REQUETES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "tennis": (
        ("INJURY", EVENEMENT, "{sujet} injury withdrawal official ATP WTA"),
        ("WITHDRAWAL", EVENEMENT, "{sujet} withdraws retires walkover tournament"),
        ("OFFICIAL_RANKING", EVENEMENT, "{sujet} official ATP WTA ranking current"),
        ("DRAW", COMPETITION, "{competition} draw order of play official"),
        ("SURFACE", COMPETITION, "{competition} surface court type official"),
    ),
    "football": (
        ("LINEUP", EVENEMENT, "{sujet} official starting lineup team news"),
        ("INJURY", EVENEMENT, "{sujet} injury list unavailable players official"),
        ("SUSPENSION", EVENEMENT, "{sujet} suspended players official"),
        ("WEATHER", COMPETITION, "{competition} match weather forecast pitch conditions"),
    ),
    "basketball": (
        ("LINEUP", EVENEMENT, "{sujet} starting lineup official"),
        ("INJURY", EVENEMENT, "{sujet} injury report official"),
        ("REST_STATUS", EVENEMENT, "{sujet} load management rest back-to-back"),
    ),
    "baseball": (
        ("LINEUP", EVENEMENT, "{sujet} probable starting pitcher official"),
        ("INJURY", EVENEMENT, "{sujet} injured list official"),
    ),
    "american_football": (
        ("INJURY", EVENEMENT, "{sujet} official injury report status"),
        ("LINEUP", EVENEMENT, "{sujet} inactives depth chart official"),
    ),
    "hockey": (
        ("INJURY", EVENEMENT, "{sujet} injury report official"),
        ("LINEUP", EVENEMENT, "{sujet} projected lineup goalie starter"),
    ),
    # `volleyball` n'a volontairement aucune requête : je ne connais pas ses
    # sources officielles de compositions et de blessures assez pour écrire une
    # requête ciblée. Mieux vaut ne rien chercher que chercher mal — une requête
    # approximative rendrait des articles de presse promus en « information ».
}


@dataclass
class _Entree:
    resultats: tuple[dict, ...]
    expire_a: float


class EnrichmentCache:
    """Cache à durée de vie, indexé par REQUÊTE et portant les résultats BRUTS.

    Il a d'abord retenu des `InternetFeature` déjà extraites. C'était une erreur
    de granularité : l'extraction filtre sur les noms de la rencontre, si bien
    que deux rencontres du même tournoi ne pouvaient pas se partager le tableau
    ou la surface — la valeur en cache appartenait à la première d'entre elles.
    Les résultats bruts, eux, ne dépendent que de la requête ; chaque rencontre
    en tire ensuite ce qui la concerne.
    """

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._ttl = ttl_seconds
        self._entrees: dict[str, _Entree] = {}
        self._verrou = Lock()

    def get(self, cle: str) -> tuple[dict, ...] | None:
        with self._verrou:
            entree = self._entrees.get(cle)
            if entree is None:
                return None
            if time.monotonic() > entree.expire_a:
                del self._entrees[cle]
                return None
            return entree.resultats

    def set(self, cle: str, resultats: Sequence[dict]) -> None:
        with self._verrou:
            self._entrees[cle] = _Entree(tuple(resultats), time.monotonic() + self._ttl)

    def __len__(self) -> int:
        with self._verrou:
            return len(self._entrees)


CACHE = EnrichmentCache()


def should_enrich(blockers: Sequence[str]) -> bool:
    """Un blocage listé, et un seul suffit."""
    return any(b in DECLENCHEURS for b in blockers)


#: Nombre de rencontres enrichies par run. Chaque rencontre coûte plusieurs
#: requêtes ; enrichir trente candidats brûlerait le quota pour un utilisateur
#: qui n'en lira que les premiers.
MAX_EVENEMENTS_ENRICHIS = 3

#: Requêtes menées de front. Borné : l'enrichissement est un service d'appoint et
#: ne doit pas saturer le quota ni la bande passante d'un coup.
_PARALLELISME = 8


def enrich_review_candidates(
    response: Any, sports: Sequence[str], *,
    limite: int = MAX_EVENEMENTS_ENRICHIS, **kw,
) -> dict[str, tuple[InternetFeature, ...]]:
    """Enrichit les premiers candidats de REVUE — et eux seuls.

    Ni les portefeuilles recommandés ni les rejetés : un BET a sa décision prise,
    un REJECTED n'a pas à être expliqué par le web. Seule la revue bénéficie d'un
    contexte externe, parce que c'est là que l'utilisateur cherche à comprendre.
    """
    from ..conversation.review_ranking import rank_review

    candidats = list(getattr(response, "review_candidates", ()) or ())
    if not candidats:
        return {}

    lignes = rank_review(candidats)[:limite]
    if not lignes:
        return {}

    recherche = kw.get("recherche", _tavily_search)
    # `or CACHE` remplaçait silencieusement un cache injecté VIDE par le cache
    # global : `EnrichmentCache` définit `__len__`, donc un cache neuf est falsy.
    # L'appelant croyait s'isoler et écrivait dans l'état partagé du processus.
    cache = kw.get("cache")
    if cache is None:
        cache = CACHE

    # UNE passe pour toutes les rencontres. Enrichir chacune dans son propre fil
    # les faisait partir ensemble, avant qu'aucune n'ait rempli le cache : les
    # requêtes de tournoi étaient émises deux fois. Rassembler les requêtes avant
    # de les lancer supprime la course au lieu d'espérer la gagner.
    travaux: dict[str, tuple[str, str]] = {}          # requête -> (sport, type)
    par_evenement: list[tuple[Any, list[tuple[str, str]]]] = []
    for ligne in lignes:
        c = ligne.candidate
        blocages = tuple(ligne.evaluation.policy_reasons) + ("INSUFFICIENT_FEATURES",)
        if not should_enrich(blocages):
            continue
        plans = _plans(c.sport, _libelle(c), _libelle_competition(c.competition_id),
                       kw.get("types"))
        par_evenement.append((c, plans))
        for feature_type, requete in plans:
            travaux.setdefault(requete, (c.sport, feature_type))

    brut = _chercher(travaux, recherche, cache)
    sortie: dict[str, tuple[InternetFeature, ...]] = {}
    for c, plans in par_evenement:
        features = _extraire(plans, brut, sport=c.sport, sujet=_libelle(c))
        if features:
            sortie[c.event_id] = features
    return sortie


def _libelle_competition(competition_id: str) -> str:
    """« competition:tennis:wta:tour » -> « WTA tour ».

    Sans cette traduction, la requête émise était littéralement
    « competition:tennis:wta:tour draw order of play » : un identifiant interne
    envoyé à un moteur de recherche. Elle rendait des pages sans rapport, qu'un
    domaine officiel suffisait ensuite à faire passer pour de l'information.
    """
    parties = [p for p in (competition_id or "").split(":") if p]
    if len(parties) < 2:
        return competition_id or ""
    interessantes = parties[2:] if parties[0] == "competition" else parties
    mots = [m for p in interessantes for m in p.replace("_", " ").split()]
    sigles = {"atp", "wta", "nba", "nhl", "nfl", "mlb", "itf", "uefa", "fifa"}
    return " ".join(m.upper() if m.lower() in sigles else m for m in mots)


def _plans(sport: str, sujet: str, competition: str,
           types: Sequence[str] | None = None) -> list[tuple[str, str]]:
    """(type de fait, requête formatée) pour un sujet — sans rien chercher."""
    gabarits = _REQUETES.get(sport, ())
    if types is not None:
        gabarits = tuple(g for g in gabarits if g[0] in types)
    return [(feature_type, gabarit.format(sujet=sujet, competition=competition or sujet))
            for feature_type, _portee, gabarit in gabarits]


def _chercher(travaux: dict[str, tuple[str, str]], recherche, cache) -> dict[str, list[dict]]:
    """Résultats BRUTS par requête : cache d'abord, réseau en parallèle ensuite.

    Les requêtes sont indépendantes ; les enchaîner faisait payer leur somme.
    Cinq requêtes à ~2,4 s coûtaient 12 s pour UNE rencontre, sur un pipeline qui
    en prend 3 au total.
    """
    brut: dict[str, list[dict]] = {}
    manquantes = []
    for requete, (sport, _type) in travaux.items():
        en_cache = cache.get(requete)
        if en_cache is not None:
            brut[requete] = list(en_cache)
        else:
            manquantes.append((requete, sport))

    if not manquantes:
        return brut

    def _une(travail):
        requete, sport = travail
        try:
            return requete, recherche(requete, official_domains(sport))
        except Exception:   # noqa: BLE001 — l'enrichissement ne casse jamais un run
            return requete, []

    with ThreadPoolExecutor(max_workers=min(_PARALLELISME, len(manquantes))) as pool:
        for requete, resultats in pool.map(_une, manquantes):
            brut[requete] = resultats or []
            cache.set(requete, brut[requete])
    return brut


def _extraire(plans: list[tuple[str, str]], brut: dict[str, list[dict]], *,
              sport: str, sujet: str) -> tuple[InternetFeature, ...]:
    """Faits d'UNE rencontre, tirés de résultats qui peuvent être partagés.

    L'extraction est par rencontre parce qu'elle filtre sur ses noms : la même
    page de tournoi ne dit pas la même chose à deux affiches différentes.
    Parcours dans l'ordre des plans — jamais dans l'ordre d'arrivée réseau.
    """
    trouvees: list[InternetFeature] = []
    for feature_type, requete in plans:
        for r in (brut.get(requete) or ())[:2]:
            url = r.get("url") or ""
            extrait = _extrait_pertinent(r, sujet)
            if not url or not extrait:
                continue
            trouvees.append(make(
                feature_type, extrait, source=r.get("title") or url,
                url=url, confidence=confidence_for(url, sport), subject=sujet))
    return tuple(sort_by_authority(trouvees))


def _extrait_pertinent(resultat: dict, sujet: str) -> str:
    """Une phrase qui PARLE du sujet, ou rien.

    Tavily rend le texte brut de la page. Sur une page officielle WTA, cela
    comprend le menu, le logo et le palmarès du tournoi — sourcé, officiel, et
    sans rapport avec la rencontre. Afficher ça sous « contexte externe » donne
    l'apparence d'une information là où il n'y a qu'une page.

    On ne garde donc qu'une phrase qui mentionne un nom du sujet. Ne rien
    afficher est préférable à afficher du remplissage : l'utilisateur ne peut pas
    distinguer un fait d'un fragment de navigation.
    """
    contenu = " ".join((resultat.get("content") or "").split())
    if not contenu:
        return ""

    noms = [m for m in re.split(r"[–\-—/]|\bvs\b", sujet) for m in [m.strip()] if len(m) > 2]
    cles = {mot.strip(".,").lower() for nom in noms for mot in nom.split()
            if len(mot.strip(".,")) >= 3}
    if not cles:
        return ""

    for phrase in re.split(r"(?<=[.!?])\s+", contenu):
        minuscule = phrase.lower()
        if any(cle in minuscule for cle in cles) and 30 <= len(phrase) <= 300:
            return phrase.strip()
    return ""


def _libelle(candidate: Any) -> str:
    """Nom lisible des participants, depuis le référentiel — jamais dérivé d'un
    identifiant, qui donnerait « player:tennis:atp:ruud_c »."""
    from ..conversation.renderer import participant_label
    return participant_label(candidate.participant_ids)


def _tavily_search(requete: str, domaines: Sequence[str]) -> list[dict]:   # pragma: no cover (réseau)
    from tavily import TavilyClient

    client = TavilyClient()
    kwargs: dict[str, Any] = {"query": requete, "max_results": 4,
                              "search_depth": "advanced"}
    if domaines:
        kwargs["include_domains"] = list(domaines)
    return client.search(**kwargs).get("results", []) or []


def enrich_event(
    *, sport: str, sujet: str, competition: str = "", blockers: Sequence[str] = (),
    recherche: Callable[[str, Sequence[str]], list[dict]] = _tavily_search,
    cache: EnrichmentCache | None = None,
    types: Sequence[str] | None = None,
) -> tuple[InternetFeature, ...]:
    """Faits externes pour UN événement bloqué, triés par autorité.

    Rien n'est renvoyé si aucun blocage listé n'est présent : c'est la garantie
    que l'enrichissement reste l'exception, pas le régime normal.
    """
    if not should_enrich(blockers):
        return ()

    plans = _plans(sport, sujet, competition, types)
    if not plans:
        return ()

    cache = cache if cache is not None else CACHE
    travaux = {requete: (sport, feature_type) for feature_type, requete in plans}
    brut = _chercher(travaux, recherche, cache)
    return _extraire(plans, brut, sport=sport, sujet=sujet)
