"""Acquisition historique multisport via api-sports — un seul chemin de code.

`ApiSportsProvider.supported_sports` valait `["football"]`. Sondée, la MÊME clé
répond HTTP 200 avec un abonnement actif sur les six produits api-sports, chacun
avec son quota propre : la limite était dans le code, pas dans le credential.

Les six produits partagent la même forme d'appel (`/games` ou `/fixtures`, filtré
par ligue et saison) et la même enveloppe (`{"response": [...]}`). Ils diffèrent
seulement par l'hôte, le nom de l'endpoint et l'endroit où vit le score. Une
seule abstraction paramétrée suffit donc, et cinq copies seraient cinq endroits
où corriger le même bug.

Ce module ACQUIERT et NORMALISE. Il ne modélise rien : les fixtures produites ont
exactement la forme que les chargeurs existants consomment déjà.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

_FIXTURES = Path(__file__).resolve().parents[5] / "tests" / "fixtures"
#: Statuts api-sports qui désignent une rencontre TERMINÉE et jouée jusqu'au
#: bout. `AOT`/`AP` (prolongation, tirs au but) en font partie ; un abandon ou un
#: report, non — on ne devine pas un résultat.
_TERMINES = frozenset({"FT", "AOT", "AP", "AET", "Game Finished",
                       "After Over Time", "Finished", "Final/OT"})


@dataclass(frozen=True)
class SportEndpoint:
    """Ce qui distingue réellement les six produits."""

    hote: str
    endpoint: str = "games"
    #: `2023-2024` chez le basket, `2023` ailleurs.
    saison_composee: bool = False


ENDPOINTS: dict[str, SportEndpoint] = {
    "basketball": SportEndpoint("v1.basketball.api-sports.io", saison_composee=True),
    "baseball": SportEndpoint("v1.baseball.api-sports.io"),
    "american-football": SportEndpoint("v1.american-football.api-sports.io"),
    "hockey": SportEndpoint("v1.hockey.api-sports.io"),
    "volleyball": SportEndpoint("v1.volleyball.api-sports.io"),
    "football": SportEndpoint("v3.football.api-sports.io", endpoint="fixtures"),
}


def _cle() -> str:
    cle = os.environ.get("API_FOOTBALL_KEY")
    if not cle:
        raise RuntimeError("API_FOOTBALL_KEY manquante — acquisition impossible")
    return cle


def fetch_games(sport: str, league_id: int, season: str, *, timeout: float = 30.0) -> list[dict]:
    """Rencontres brutes d'une ligue-saison. Aucune transformation ici."""
    import requests

    spec = ENDPOINTS[sport]
    reponse = requests.get(
        f"https://{spec.hote}/{spec.endpoint}",
        headers={"x-apisports-key": _cle()},
        params={"league": league_id, "season": season},
        timeout=timeout,
    )
    reponse.raise_for_status()
    charge = reponse.json()
    erreurs = charge.get("errors")
    if erreurs and not isinstance(erreurs, list):
        raise RuntimeError(f"api-sports {sport} {league_id}/{season} : {erreurs}")
    return charge.get("response") or []


# ── Normalisation vers les formes déjà consommées ─────────────────────────────
def _plat(jeu: dict) -> dict:
    """Le produit american-football imbrique id, date et statut sous `game` ;
    les autres les exposent à plat. On aplanit une fois, ici, plutôt que de
    dupliquer la condition dans chaque accesseur."""
    interne = jeu.get("game")
    return {**jeu, **interne} if isinstance(interne, dict) else jeu


def _statut(jeu: dict) -> str:
    statut = _plat(jeu).get("status") or {}
    if not isinstance(statut, dict):
        return str(statut)
    # `Final/OT` arrive avec `short=None` : le libellé long est alors la seule
    # information disponible, et l'ignorer écartait 13 rencontres réelles.
    return statut.get("short") or statut.get("long") or ""


def _instant(jeu: dict) -> str | None:
    date = _plat(jeu).get("date")
    if isinstance(date, dict):
        horodatage = date.get("timestamp")
        if horodatage:
            return datetime.fromtimestamp(int(horodatage), tz=timezone.utc).isoformat()
        jour, heure = date.get("date"), date.get("time") or "00:00"
        return f"{jour}T{heure}:00+00:00" if jour else None
    if isinstance(date, str) and date:
        return date
    horodatage = _plat(jeu).get("timestamp")
    if horodatage:
        return datetime.fromtimestamp(int(horodatage), tz=timezone.utc).isoformat()
    return None


def _total(cote: Any) -> int | None:
    """Le score total, quel que soit l'endroit où le produit le range."""
    if isinstance(cote, (int, float)):
        return int(cote)
    if isinstance(cote, dict):
        for champ in ("total", "points", "score"):
            valeur = cote.get(champ)
            if isinstance(valeur, (int, float)):
                return int(valeur)
    return None


def _equipes(jeu: dict) -> tuple[dict, dict]:
    equipes = jeu.get("teams") or {}
    return equipes.get("home") or {}, equipes.get("away") or {}


def _scores(jeu: dict) -> tuple[int | None, int | None]:
    scores = jeu.get("scores") or {}
    return _total(scores.get("home")), _total(scores.get("away"))


def normalise_pairwise(jeux: Iterable[dict], *, cles_courtes: bool) -> list[dict]:
    """Forme `{id, date, home*, away*, score}` des fixtures pairwise existantes.

    `cles_courtes` distingue les deux conventions déjà présentes dans le dépôt :
    `home_id/home_pts` (NBA, MLB) et `home/hs` (NFL, volley). On s'aligne sur
    l'existant plutôt que d'imposer une troisième convention et de réécrire des
    chargeurs qui fonctionnent.
    """
    sortie: list[dict] = []
    for jeu in jeux:
        if _statut(jeu) not in _TERMINES:
            continue
        domicile, exterieur = _equipes(jeu)
        sd, se = _scores(jeu)
        date = _instant(jeu)
        if None in (sd, se, date) or not domicile.get("id") or not exterieur.get("id"):
            continue
        if sd == se:
            continue          # nul : hors marché 2-way, jamais arbitré au hasard
        if cles_courtes:
            sortie.append({"id": _plat(jeu).get("id"), "date": date,
                           "home": domicile["id"], "away": exterieur["id"],
                           "home_name": domicile.get("name"), "away_name": exterieur.get("name"),
                           "hs": sd, "as": se})
        else:
            sortie.append({"id": _plat(jeu).get("id"), "date": date,
                           "home_id": domicile["id"], "away_id": exterieur["id"],
                           "home_name": domicile.get("name"), "away_name": exterieur.get("name"),
                           "home_pts": sd, "away_pts": se})
    return sortie


def normalise_hockey_regulation(jeux: Iterable[dict]) -> list[dict]:
    """Hockey : issue du TEMPS RÉGLEMENTAIRE, nul inclus.

    Le modèle NHL est un Davidson 3-way — le nul y est une issue à part entière,
    pas un cas écarté. On ne retient donc que les rencontres décidées dans le
    temps réglementaire ; celles allant en prolongation ont un nul à 60 minutes,
    ce que `periods` permet de lire quand le produit l'expose.
    """
    sortie: list[dict] = []
    for jeu in jeux:
        if _statut(jeu) not in _TERMINES:
            continue
        domicile, exterieur = _equipes(jeu)
        date = _instant(jeu)
        if not date or not domicile.get("id") or not exterieur.get("id"):
            continue
        scores = jeu.get("scores") or {}
        periodes = jeu.get("periods") or {}
        reglementaire = periodes.get("third") or ""
        if isinstance(reglementaire, str) and "-" in reglementaire:
            try:
                sd, se = (int(x) for x in reglementaire.split("-", 1))
            except ValueError:
                continue
        else:
            sd, se = _total(scores.get("home")), _total(scores.get("away"))
            # Prolongation : le score final ne dit plus l'issue réglementaire.
            if _statut(jeu) in ("AOT", "AP", "AET"):
                sd = se = None
        if sd is None or se is None:
            continue
        issue = "home" if sd > se else ("away" if se > sd else "draw")
        sortie.append({"id": _plat(jeu).get("id"), "date": date,
                       "home": domicile["id"], "away": exterieur["id"], "o": issue})
    return sortie


# ── Écriture des fixtures ─────────────────────────────────────────────────────
def acquire(
    sport: str, league_id: int, saisons: Iterable[str], cible: str,
    *, normaliseur: Callable[[Iterable[dict]], list[dict]],
    pause: float = 1.5, journal: Callable[[str], None] = print,
) -> int:
    """Acquiert plusieurs saisons et écrit UNE fixture, provenance incluse.

    Les rencontres sont triées chronologiquement : le rejeu walk-forward suppose
    que le passé précède le présent, et un fichier mal ordonné ferait prédire une
    saison avec des notes acquises plus tard.
    """
    toutes: list[dict] = []
    acquises: list[str] = []
    for saison in saisons:
        bruts = fetch_games(sport, league_id, saison)
        normalises = normaliseur(bruts)
        journal(f"  {sport} {league_id} {saison} : {len(bruts)} bruts -> {len(normalises)} retenus")
        if normalises:
            toutes.extend(normalises)
            acquises.append(str(saison))
        time.sleep(pause)

    toutes.sort(key=lambda j: j["date"])
    vus, uniques = set(), []
    for jeu in toutes:                      # idempotence : un id ne compte qu'une fois
        if jeu["id"] in vus:
            continue
        vus.add(jeu["id"])
        uniques.append(jeu)

    (_FIXTURES / cible).write_text(json.dumps({
        "provenance": {
            "provider": "api_sports",
            "sport": sport,
            "league_id": league_id,
            "seasons": acquises,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status_filter": sorted(_TERMINES),
        },
        "games": uniques,
    }, ensure_ascii=False), encoding="utf-8")
    return len(uniques)
