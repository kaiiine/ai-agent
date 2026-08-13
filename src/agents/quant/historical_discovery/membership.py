"""Alimenter le référentiel saisonnier depuis un backfill historique.

Le référentiel sait répondre « qui joue quoi, quand » — encore faut-il que
quelqu'un le remplisse. Il était construit dans les tests et nulle part ailleurs :
une garantie non alimentée protège exactement zéro rencontre, et un test vert
rend cet écart invisible.

Le backfill est la bonne source. Il apporte des rencontres RÉELLEMENT observées,
compétition et saison comprises — précisément ce dont l'appartenance se déduit.
Aucune liste à tenir à la main, donc aucune liste à oublier.

L'EFFECTIF COMPLET NE SE DÉCLARE PAS À LA LÉGÈRE. C'est la seule porte vers un
`NOT_ACTIVE`, donc vers un rejet. On ne la franchit que pour une saison dont on
a ingéré la compétition ENTIÈRE — pas un extrait, pas une fenêtre de dates. Le
critère est explicite (`saisons_completes`) plutôt que déduit d'un volume, parce
qu'un seuil au jugé finirait par déclarer complète une saison tronquée.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.agents.quant.gateway.core.seasonal_membership import (
    SeasonalMembershipRegistry)


@dataclass(frozen=True)
class _Rencontre:
    """Vue minimale qu'attend `ingest_matches` — évite de dépendre du schéma
    football alors que le backfill est multisport."""

    league_id: str
    season: str
    home_team_id: str
    away_team_id: str
    kickoff: object


def alimenter(
    registry: SeasonalMembershipRegistry, evidences, *,
    participants_de=None, saisons_completes=(),
) -> dict:
    """Déverse des observations historiques dans le référentiel saisonnier.

    `participants_de(e)` rend les identités CANONIQUES ; sans elles, on
    enregistrerait des libellés de source comme s'ils étaient des entités, et le
    référentiel répondrait `UNKNOWN` sur des clubs pourtant connus.

    `saisons_completes` : les `(competition, saison)` dont on affirme avoir tout
    ingéré. Rien d'autre n'autorise un démenti.
    """
    if participants_de is None:
        participants_de = lambda e: tuple(e.participants)      # noqa: E731

    rencontres, ignorees = [], 0
    par_saison: dict[tuple[str, str], int] = defaultdict(int)
    for e in evidences:
        if not e.is_learnable:
            ignorees += 1
            continue
        ids = participants_de(e)
        if ids is None or len(ids) < 2 or any(i is None for i in ids):
            ignorees += 1
            continue
        rencontres.append(_Rencontre(e.competition, e.season, ids[0], ids[1],
                                     e.scheduled_at))
        par_saison[(e.competition, e.season)] += 1

    registry.ingest_matches(rencontres)
    for competition, saison in saisons_completes:
        registry.mark_roster_complete(competition, saison)

    return {
        "ingerees": len(rencontres),
        "ignorees": ignorees,
        "saisons_vues": len(par_saison),
        "saisons_completes": len(tuple(saisons_completes)),
        "entrees_referentiel": len(registry),
    }


def saison_football_europeenne(instant) -> str:
    """Saison d'une compétition européenne à cheval sur deux années civiles.

    Juillet est la charnière : une rencontre de septembre 2025 appartient à la
    saison 2025, une rencontre de mai 2026 aussi. Prendre l'année civile
    couperait chaque saison en deux au 1ᵉʳ janvier, et un club changerait
    d'appartenance au milieu de sa campagne.
    """
    return str(instant.year if instant.month >= 7 else instant.year - 1)


def saison_annee_civile(instant) -> str:
    """Ligues nord-américaines et sud-américaines dont la saison tient dans une
    année civile. Appliquer la règle européenne y décalerait tout d'un an."""
    return str(instant.year)
