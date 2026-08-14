"""Le modèle a-t-il des données sur la population ACTUELLE de cet événement ?

L'identité d'une équipe est stable ; son appartenance au domaine d'un modèle ne
l'est pas. Frosinone reste Frosinone après une relégation — mais le corpus Serie A
cesse de la décrire, et le modèle continue pourtant de répondre, avec des forces
calculées sur une saison vieille de deux ans.

MESURÉ, sur six rencontres réelles de Serie A servies par le catalogue live :

    atalanta 84   sassuolo 82      bologna 83   lazio 83
    genoa    82   napoli   82      parma   82   cagliari 82
    inter    83   MONZA   447      FROSINONE 810   juventus 82

Les deux valeurs aberrantes sont exactement les deux équipes reléguées. Il n'y a
aucun cas intermédiaire : la coupure ne se négocie pas, elle se lit.

CE GARDE-FOU NE REGARDE PAS L'ESPÉRANCE. Une grosse EV peut être réelle ; elle ne
prouve rien, ni dans un sens ni dans l'autre. Ce qui est vérifié ici est une
propriété des DONNÉES — l'âge de la dernière observation utilisée — et elle
serait tout aussi disqualifiante devant une EV médiocre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DomainStatus(str, Enum):
    IN_DOMAIN = "IN_DOMAIN"
    #: Un participant n'a aucune observation dans le domaine courant : il a
    #: changé de division, ou le corpus ne couvre plus sa compétition. Le modèle
    #: répond quand même — c'est précisément le danger.
    INSUFFICIENT_CURRENT_DOMAIN_HISTORY = "INSUFFICIENT_CURRENT_DOMAIN_HISTORY"
    #: L'âge n'est pas mesurable : on ne conclut ni dans un sens ni dans l'autre.
    NOT_MEASURABLE = "NOT_MEASURABLE"


#: Un cycle annuel — la PÉRIODE de la compétition, pas une constante réglée. Une
#: équipe dont la dernière rencontre observée date de plus d'un an n'a pas joué
#: la saison écoulée dans ce corpus : elle en est sortie. La mesure ci-dessus
#: montre que la population réelle se sépare très au-delà de cette borne
#: (84 jours d'un côté, 447 de l'autre), donc la valeur exacte n'est pas
#: discriminante — c'est l'ordre de grandeur qui l'est.
CYCLE_SAISON_JOURS = 365

#: Le champ de features qui porte l'âge. Il existait déjà et n'était lu par
#: personne : `rest_days` valait 810 sans que `missing_features` ne signale quoi
#: que ce soit.
CHAMP_AGE = "rest_days"


@dataclass(frozen=True)
class DomainCheck:
    status: DomainStatus
    reason: str = ""
    #: participant -> âge en jours de sa dernière observation.
    ages: dict = field(default_factory=dict)
    hors_domaine: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.status is DomainStatus.IN_DOMAIN


def verifier_domaine(event, features, *, cycle_jours: int = CYCLE_SAISON_JOURS) -> DomainCheck:
    """Chaque participant a-t-il une observation dans le cycle courant ?

    `NOT_MEASURABLE` quand l'âge n'est pas disponible : c'est un troisième état,
    et il ne doit pas se confondre avec un feu vert. Un appelant qui l'ignore
    price comme avant ; un appelant prudent s'abstient.
    """
    ages: dict[str, float] = {}
    for participant in getattr(event, "participants", ()) or ():
        cid = participant.canonical_id
        valeur = (features.participant_features.get(cid) or {}).get(CHAMP_AGE)
        if valeur is not None:
            ages[cid] = float(valeur)

    if not ages:
        return DomainCheck(DomainStatus.NOT_MEASURABLE,
                           f"aucun `{CHAMP_AGE}` disponible : l'appartenance au domaine "
                           "courant n'est pas vérifiable")

    hors = tuple(sorted(cid for cid, age in ages.items() if age > cycle_jours))
    if hors:
        detail = ", ".join(f"{cid} ({ages[cid]:.0f} j)" for cid in hors)
        return DomainCheck(
            DomainStatus.INSUFFICIENT_CURRENT_DOMAIN_HISTORY,
            f"aucune rencontre observée depuis plus d'un cycle de compétition "
            f"({cycle_jours} j) pour : {detail}. L'identité de l'équipe n'a pas "
            "changé ; son appartenance au domaine du modèle, si.",
            ages, hors)

    return DomainCheck(DomainStatus.IN_DOMAIN,
                       "tous les participants ont une observation dans le cycle courant",
                       ages)
