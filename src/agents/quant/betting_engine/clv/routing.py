"""À QUEL modèle appartient une observation de cote.

L'historique est unique et multisport ; les modèles, eux, sont évalués un par un.
Sans aiguillage, deux erreurs opposées guettent : ne rien passer — et le critère
`positive_clv` reste à zéro pendant que l'historique se remplit — ou tout passer,
et le modèle NHL se voit créditer des paires de baseball.

L'aiguillage lit l'identité canonique de l'événement, qui porte déjà son sport et
sa compétition : `event:baseball:mlb:…`. Aucune table parallèle, aucune
convention nouvelle.

Le tennis fait exception et mérite qu'on l'explique. Sa compétition canonique est
le CIRCUIT (`competition:tennis:atp:tour`), dont le slug est `tour` — identique
pour l'ATP et la WTA. L'identité d'événement ne suffit donc pas à les séparer.
Ce qui les sépare, c'est le référentiel des joueurs : `player:tennis:atp:ruud_c`
n'existe que sur un circuit. On y résout donc les participants, plutôt que de
verser les mêmes paires aux deux modèles — ce qui reviendrait à mesurer l'ATP
avec des matchs de la WTA.
"""

from __future__ import annotations

import functools
from typing import Sequence

#: Clé de readiness -> (sport, slugs de compétition acceptés). Un modèle absent
#: d'ici ne reçoit aucune observation : mieux vaut un critère qui n'avance pas
#: qu'un critère nourri par les paires d'un autre sport.
ROUTES: dict[str, tuple[str, tuple[str, ...]]] = {
    "fl1": ("football", ("ligue1",)),
    "serie-a": ("football", ("serie_a",)),
    "laliga": ("football", ("laliga",)),
    "bundesliga": ("football", ("bundesliga",)),
    "championship": ("football", ("championship",)),
    "eredivisie": ("football", ("eredivisie",)),
    "primeira-liga": ("football", ("primeira_liga",)),
    "nba": ("basketball", ("nba",)),
    "mlb": ("baseball", ("mlb",)),
    "nfl": ("american_football", ("nfl",)),
    "nhl": ("hockey", ("nhl",)),
    "volley": ("volleyball", ("serie_a1",)),
    "atp": ("tennis", ("tour",)),
    "wta": ("tennis", ("tour",)),
}


def _decompose(event_id: str) -> tuple[str, str, str]:
    """`event:baseball:mlb:2026-…:home=x|away=y` -> (sport, compétition, rôles)."""
    parties = (event_id or "").split(":")
    if len(parties) < 4 or parties[0] != "event":
        return "", "", ""
    return parties[1], parties[2], parties[-1]


@functools.lru_cache(maxsize=1)
def _circuit_par_joueur() -> dict[str, str]:
    """slug de joueur -> circuit, depuis le référentiel tennis."""
    from ..sports.registry import SPORT_MODULES

    module = SPORT_MODULES.get("tennis")
    if module is None:
        return {}
    par_slug: dict[str, str] = {}
    for entite in module.known_entities():
        parties = entite.canonical_id.split(":")
        if len(parties) >= 4 and parties[0] == "player":
            par_slug[parties[3]] = parties[2]
    return par_slug


def _circuit_de(roles: str) -> str | None:
    """Circuit d'une rencontre de tennis, résolu par ses joueurs.

    Les deux joueurs doivent s'accorder : un plateau mixte — ou un joueur inconnu
    du référentiel — ne permet pas de trancher, et attribuer la rencontre au
    hasard fausserait l'un des deux modèles.
    """
    par_slug = _circuit_par_joueur()
    circuits = set()
    for morceau in roles.split("|"):
        _, _, slug = morceau.partition("=")
        circuit = par_slug.get(slug)
        if circuit is None:
            return None
        circuits.add(circuit)
    return circuits.pop() if len(circuits) == 1 else None


def observations_pour(cle: str, observations: Sequence) -> list:
    """Les observations qui appartiennent RÉELLEMENT à ce modèle."""
    route = ROUTES.get(cle)
    if route is None:
        return []
    sport, competitions = route

    retenues = []
    for obs in observations:
        obs_sport, obs_competition, roles = _decompose(obs.event_id)
        if obs_sport != sport or obs_competition not in competitions:
            continue
        if sport == "tennis" and _circuit_de(roles) != cle:
            continue
        retenues.append(obs)
    return retenues
