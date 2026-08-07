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

import time
from dataclasses import dataclass
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

#: Requêtes CIBLÉES par sport. Jamais « actualités tennis » : une recherche
#: générique rend des articles d'opinion, et c'est exactement ce qu'on ne veut
#: pas voir remonter comme « information ».
_REQUETES: dict[str, tuple[tuple[str, str], ...]] = {
    "tennis": (
        ("INJURY", "{sujet} injury withdrawal official ATP WTA"),
        ("WITHDRAWAL", "{sujet} withdraws retires walkover tournament"),
        ("OFFICIAL_RANKING", "{sujet} official ATP WTA ranking current"),
        ("DRAW", "{competition} draw order of play official"),
        ("SURFACE", "{competition} surface court type official"),
    ),
    "football": (
        ("LINEUP", "{sujet} official starting lineup team news"),
        ("INJURY", "{sujet} injury list unavailable players official"),
        ("SUSPENSION", "{sujet} suspended players official"),
        ("WEATHER", "{competition} match weather forecast pitch conditions"),
    ),
    "basketball": (
        ("LINEUP", "{sujet} starting lineup official"),
        ("INJURY", "{sujet} injury report official"),
        ("REST_STATUS", "{sujet} load management rest back-to-back"),
    ),
    "baseball": (
        ("LINEUP", "{sujet} probable starting pitcher official"),
        ("INJURY", "{sujet} injured list official"),
    ),
    "american_football": (
        ("INJURY", "{sujet} official injury report status"),
        ("LINEUP", "{sujet} inactives depth chart official"),
    ),
    "hockey": (
        ("INJURY", "{sujet} injury report official"),
        ("LINEUP", "{sujet} projected lineup goalie starter"),
    ),
    # `volleyball` n'a volontairement aucune requête : je ne connais pas ses
    # sources officielles de compositions et de blessures assez pour écrire une
    # requête ciblée. Mieux vaut ne rien chercher que chercher mal — une requête
    # approximative rendrait des articles de presse promus en « information ».
}


@dataclass
class _Entree:
    features: tuple[InternetFeature, ...]
    expire_a: float


class EnrichmentCache:
    """Cache à durée de vie. Une blessure annoncée ne change pas toutes les
    minutes ; réinterroger le web à chaque rendu brûlerait le quota sans rien
    apprendre."""

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._ttl = ttl_seconds
        self._entrees: dict[str, _Entree] = {}

    def get(self, cle: str) -> tuple[InternetFeature, ...] | None:
        entree = self._entrees.get(cle)
        if entree is None:
            return None
        if time.monotonic() > entree.expire_a:
            del self._entrees[cle]
            return None
        return entree.features

    def set(self, cle: str, features: Sequence[InternetFeature]) -> None:
        self._entrees[cle] = _Entree(tuple(features), time.monotonic() + self._ttl)

    def __len__(self) -> int:
        return len(self._entrees)


CACHE = EnrichmentCache()


def should_enrich(blockers: Sequence[str]) -> bool:
    """Un blocage listé, et un seul suffit."""
    return any(b in DECLENCHEURS for b in blockers)


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

    plans = _REQUETES.get(sport, ())
    if types is not None:
        plans = tuple(p for p in plans if p[0] in types)
    if not plans:
        return ()

    cache = cache if cache is not None else CACHE
    cle = f"{sport}|{sujet}|{competition}|{','.join(t for t, _ in plans)}"
    en_cache = cache.get(cle)
    if en_cache is not None:
        return en_cache

    officiels = official_domains(sport)
    trouvees: list[InternetFeature] = []
    for feature_type, gabarit in plans:
        requete = gabarit.format(sujet=sujet, competition=competition or sujet)
        try:
            resultats = recherche(requete, officiels)
        except Exception:   # noqa: BLE001 — l'enrichissement ne casse jamais un run
            continue
        for r in resultats[:2]:
            url = r.get("url") or ""
            extrait = (r.get("content") or r.get("title") or "").strip()
            if not url or not extrait:
                continue
            trouvees.append(make(
                feature_type, extrait[:300], source=r.get("title") or url,
                url=url, confidence=confidence_for(url, sport), subject=sujet))

    resultat = tuple(sort_by_authority(trouvees))
    cache.set(cle, resultat)
    return resultat
