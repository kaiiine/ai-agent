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
# Les accesseurs de forme brute vivent dans la couche basse : la Gateway les
# utilise pour normaliser, l'acquisition pour écrire ses fixtures. Une seule
# définition — chaque particularité qu'ils encodent a coûté des rencontres
# perdues avant d'être vue.
from src.agents.quant.gateway.providers.api_sports_shape import (  # noqa: E402
    TERMINES as _TERMINES,
    aplatir as _plat,
    equipes as _equipes,
    instant as _instant,
    scores as _scores,
    statut as _statut,
)


#: Les six produits sont décrits UNE fois, côté Gateway
#: (`gateway/providers/api_sports_provider.PRODUITS`). Ce module les lisait dans
#: sa propre table : la même connaissance à deux endroits, donc deux endroits à
#: corriger le jour où un hôte change. La Gateway est la couche basse — c'est
#: elle qui porte la table, et l'acquisition la consulte.
#:
#: Les clés canoniques du produit utilisent `american_football` ; l'API et les
#: scripts d'ingestion existants écrivent `american-football`. Les deux sont
#: acceptées ici pour ne pas casser une commande déjà écrite.
def _produit(sport: str):
    from src.agents.quant.gateway.providers.api_sports_provider import PRODUITS

    return PRODUITS[sport.replace("-", "_")]


def _cle() -> str:
    cle = os.environ.get("API_FOOTBALL_KEY")
    if not cle:
        raise RuntimeError("API_FOOTBALL_KEY manquante — acquisition impossible")
    return cle


def fetch_games(sport: str, league_id: int, season: str, *, timeout: float = 30.0) -> list[dict]:
    """Rencontres brutes d'une ligue-saison. Aucune transformation ici."""
    import requests

    spec = _produit(sport)
    reponse = requests.get(
        f"{spec.hote}/{spec.endpoint}",
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
