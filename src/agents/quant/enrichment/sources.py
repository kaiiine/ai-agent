"""Hiérarchie des sources — l'officiel avant la presse.

Une blessure annoncée par l'ATP et la même annoncée par un blog n'ont pas le même
statut, et les afficher côte à côte sans distinction reviendrait à dire qu'elles
se valent. Le classement est déclaré ici, pas déduit d'un score de pertinence
web : c'est un choix éditorial, il doit se lire.
"""

from __future__ import annotations

from urllib.parse import urlparse

OFFICIAL = "OFFICIAL"
REPUTABLE = "REPUTABLE"
UNVERIFIED = "UNVERIFIED"

#: Domaines des instances qui ORGANISENT la compétition — elles ne rapportent pas
#: l'information, elles la produisent.
_OFFICIELS: dict[str, tuple[str, ...]] = {
    "tennis": ("atptour.com", "wtatennis.com", "itftennis.com", "usopen.org",
               "wimbledon.com", "rolandgarros.com", "ausopen.com"),
    "football": ("fifa.com", "uefa.com", "premierleague.com", "ligue1.fr",
                 "legaseriea.it", "laliga.com", "bundesliga.com", "eredivisie.nl",
                 "ligaportugal.pt", "efl.com"),
    "basketball": ("nba.com", "euroleaguebasketball.net", "fiba.basketball"),
    "baseball": ("mlb.com",),
    "american_football": ("nfl.com",),
    "hockey": ("nhl.com", "iihf.com"),
    "volleyball": ("fivb.com", "cev.eu", "legavolley.it"),
}

#: Agences et médias sportifs de référence. Reconnus, mais rapporteurs.
_RECONNUS = ("reuters.com", "apnews.com", "espn.com", "bbc.com", "lequipe.fr",
             "skysports.com", "eurosport.fr", "rmcsport.bfmtv.com")


def _domaine(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def confidence_for(url: str, sport: str | None = None) -> str:
    """Niveau de confiance d'une URL. Jamais mieux que ce que le domaine permet."""
    domaine = _domaine(url)
    if not domaine:
        return UNVERIFIED

    officiels = _OFFICIELS.get(sport, ()) if sport else tuple(
        d for liste in _OFFICIELS.values() for d in liste)
    if any(domaine == d or domaine.endswith("." + d) for d in officiels):
        return OFFICIAL
    if any(domaine == d or domaine.endswith("." + d) for d in _RECONNUS):
        return REPUTABLE
    return UNVERIFIED


_ORDRE = {OFFICIAL: 0, REPUTABLE: 1, UNVERIFIED: 2}


def sort_by_authority(features):
    """Trie par autorité décroissante, puis par fraîcheur. Un fait officiel
    ancien reste prioritaire sur une rumeur récente."""
    return sorted(features, key=lambda f: (_ORDRE.get(f.confidence, 3), -f.retrieved_at.timestamp()))


def official_domains(sport: str) -> tuple[str, ...]:
    return _OFFICIELS.get(sport, ())
