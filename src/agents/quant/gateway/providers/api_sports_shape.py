"""Forme BRUTE d'une rencontre api-sports, tous produits confondus.

Les six produits décrivent la même chose — deux équipes, un score, un instant, un
statut — de six façons légèrement différentes. Ces accesseurs ont été écrits et
éprouvés contre des payloads réels pendant l'acquisition historique : le produit
american-football imbrique tout sous `game`, `Final/OT` arrive avec `short=None`,
le basket range son score sous `{"total": …}`, le baseball horodate par
`timestamp`. Chacune de ces particularités a coûté des rencontres perdues avant
d'être vue.

Ils vivent ICI, dans la couche basse, parce que deux couches en ont besoin : la
Gateway pour normaliser vers les faits canoniques, l'acquisition pour écrire ses
fixtures d'entraînement. Les garder dans l'acquisition aurait obligé la Gateway à
importer une couche supérieure, ou à les réécrire — et une réécriture, ici,
signifie re-perdre les mêmes rencontres.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: Statuts qui désignent une rencontre TERMINÉE et jouée jusqu'au bout.
#: `AOT`/`AP` (prolongation, tirs au but) en font partie ; un abandon ou un
#: report, non — on ne devine pas un résultat.
TERMINES = frozenset({"FT", "AOT", "AP", "AET", "Game Finished",
                      "After Over Time", "Finished", "Final/OT"})


def aplatir(jeu: dict) -> dict:
    """Le produit american-football imbrique id, date et statut sous `game` ;
    les autres les exposent à plat. On aplanit une fois, ici, plutôt que de
    dupliquer la condition dans chaque accesseur."""
    interne = jeu.get("game")
    return {**jeu, **interne} if isinstance(interne, dict) else jeu


def statut(jeu: dict) -> str:
    valeur = aplatir(jeu).get("status") or {}
    if not isinstance(valeur, dict):
        return str(valeur)
    # `Final/OT` arrive avec `short=None` : le libellé long est alors la seule
    # information disponible, et l'ignorer écartait 13 rencontres réelles.
    return valeur.get("short") or valeur.get("long") or ""


def instant(jeu: dict) -> str | None:
    date = aplatir(jeu).get("date")
    if isinstance(date, dict):
        horodatage = date.get("timestamp")
        if horodatage:
            return datetime.fromtimestamp(int(horodatage), tz=timezone.utc).isoformat()
        jour, heure = date.get("date"), date.get("time") or "00:00"
        return f"{jour}T{heure}:00+00:00" if jour else None
    if isinstance(date, str) and date:
        return date
    horodatage = aplatir(jeu).get("timestamp")
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


def equipes(jeu: dict) -> tuple[dict, dict]:
    table = jeu.get("teams") or {}
    return table.get("home") or {}, table.get("away") or {}


def scores(jeu: dict) -> tuple[int | None, int | None]:
    table = jeu.get("scores") or {}
    return _total(table.get("home")), _total(table.get("away"))


def identifiant(jeu: dict) -> Any:
    return aplatir(jeu).get("id")
