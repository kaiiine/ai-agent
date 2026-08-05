"""Identité de compétition du tennis — déduite du PLATEAU, jamais du tid ni du nom.

Le tennis casse l'hypothèse des sports de ligue : chez Winamax, le `raw_tournament_id`
identifie *une édition d'un tournoi* (176503 = Montréal 2026), pas une compétition
stable. Le mapper statiquement vers une identité canonique donnerait une table à
réécrire chaque semaine — fragile par construction, et fausse dès la semaine suivante.

Le nom ne vaut pas mieux. Le Canadian Open ALTERNE les villes entre circuits : en 2026
Winamax place l'ATP à Montréal et la WTA à Toronto, l'inverse de l'année précédente.
Résoudre « Toronto » vers un circuit ferait tourner un modèle masculin sur des matchs
féminins une année sur deux — misresolution silencieuse, money-sensitive.

Ce qui EST stable, c'est le plateau : les joueurs d'un événement appartiennent à un
circuit et à un seul. On résout donc par la preuve, avec la même primitive que le
football (`competition_identity.disambiguate`) : les noms observés doivent recouvrir
le roster d'un circuit et devancer nettement l'autre. Aucun candidat assez recouvrant,
ou deux candidats trop proches -> non résolu, jamais deviné.
"""

from __future__ import annotations

from ...competition_identity import (
    COMPETITION_IDENTITY_RESOLVED,
    disambiguate,
)

TOURS = ("atp", "wta")

# Un circuit = une population de joueurs et un pool de notes Elo. C'est ce que le
# modèle consomme ; le tournoi lui-même n'entre dans aucune feature.
COMPETITION_IDS = {tour: f"competition:tennis:{tour}:tour" for tour in TOURS}

# Deux joueurs seulement par événement : le recouvrement est donc 0, 0.5 ou 1.
# Exiger la TOTALITÉ (1.0) et une marge pleine revient à demander que les DEUX
# joueurs soient connus du même circuit. Un seul reconnu (0.5) laisse la porte
# ouverte à un adversaire d'un autre circuit ou absent du référentiel : dans les
# deux cas la note Elo serait prise dans le mauvais pool, ou fabriquée.
_MIN_OVERLAP = 1.0
_MIN_MARGIN = 0.5


def _rosters() -> dict[str, list[str]]:
    from .identity import tennis_players

    rosters: dict[str, list[str]] = {}
    for tour in TOURS:
        entities, _ = tennis_players(tour)
        rosters[COMPETITION_IDS[tour]] = [e.canonical_name for e in entities]
    return rosters


def resolve_tennis_competition(event) -> tuple[str | None, str, str]:
    """`RawBookmakerEvent` -> `(competition_id, statut, méthode)`.

    Même contrat de retour que le résolveur par tid des sports de ligue, pour que
    le registre d'événements n'ait pas à savoir de quel sport il s'agit.
    """
    observed = [n for n in (event.slot_1_name, event.slot_2_name) if n]
    if len(observed) != 2:
        return None, "UNRESOLVED", "roster_overlap"

    resolution = disambiguate(observed, _rosters(),
                              min_overlap=_MIN_OVERLAP, min_margin=_MIN_MARGIN)
    if resolution.status == COMPETITION_IDENTITY_RESOLVED:
        return resolution.competition_id, "RESOLVED", "roster_overlap"
    # AMBIGUOUS (deux circuits également recouvrants) comme UNRESOLVED (aucun) :
    # dans les deux cas on ne SAIT pas, et le registre ne doit pas trancher.
    return None, "UNRESOLVED", "roster_overlap"
