"""Quelles observations ont le droit de PROUVER une maturité.

L'historique est un journal immuable : tout ce qui a été observé y reste, et rien
n'y est corrigé. Mais toutes les observations n'ont pas la même sémantique, et
les mélanger dans une preuve de maturité reviendrait à mesurer autre chose que ce
qu'on croit.

Le cas qui a motivé ce module : 45 décisions NHL prises **55 jours** avant leur
coup d'envoi, par les captures manuelles antérieures au collecteur. Leur CLV,
quand elle se formera, mesurera deux mois de dérive de marché — pas l'avance d'une
décision sur sa clôture. Six décisions tennis dépassent également l'horizon.

Ces observations ne sont ni fausses ni à supprimer. Elles sont simplement hors du
protocole de collecte actuel, et une preuve doit porter sur un protocole unique.

LA FENÊTRE N'EST PAS CHOISIE ICI. Elle est DÉRIVÉE de la policy du collecteur —
`FENETRE_CLOTURE` et `HORIZON_DECISION` — parce que c'est elle qui définit ce
qu'AXON appelle aujourd'hui une décision et une clôture. Inventer un seuil propre
à la preuve permettrait de le régler jusqu'à obtenir le résultat voulu ; le
dériver interdit ce geste.

Aucune donnée n'est migrée : le temps d'avance se RECONSTRUIT depuis l'identité
canonique de l'événement, qui porte déjà son coup d'envoi.

SECOND CAS, DE MÊME NATURE : LA DÉRIVE D'HORAIRE. Une cote relevée à 18 h 13
alors que le départ était annoncé à 18 h 30 a été honnêtement classée CLOSING —
17 minutes d'avance, dans la fenêtre. Si Winamax repousse ensuite le match à
18 h 50, cette observation reste ce qu'elle était : on ne la reclasse pas, on ne
la réécrit pas, elle demeure une CLOSING dans le store. Mais elle a cessé de
mesurer une ligne de clôture, et s'en servir comme référence de CLV serait faux.

Mesuré : 10 des 12 paires tennis reposaient sur une telle observation, l'une
d'elles capturée 20 heures avant le départ réel d'un match reporté au lendemain.

    classification historique  ≠  admissibilité à la preuve

D'où le verdict `CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW`, distinct des autres : la
fenêtre reste `FENETRE_CLOTURE`, inchangée — c'est la RÉFÉRENCE qui change, du
coup d'envoi annoncé sur le moment au dernier coup d'envoi connu pour cette
rencontre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .collect import FENETRE_CLOTURE, HORIZON_DECISION
from .identity import (
    HistoriqueHoraires,
    historique_horaires,
    kickoff_de,
    stable_event_id,
)
from .observation import ObservationPhase

#: Version du protocole de collecte auquel une observation est confrontée.
#: Change dès que la fenêtre ou l'horizon changent — deux cohortes régies par des
#: règles différentes ne doivent jamais être additionnées en silence.
POLICY_VERSION = (f"collect/v1:closing<={int(FENETRE_CLOTURE.total_seconds() // 60)}min"
                  f":decision<={int(HORIZON_DECISION.total_seconds() // 3600)}h")

ELIGIBLE = "ELIGIBLE"
LEGACY_DECISION_HORIZON = "LEGACY_DECISION_HORIZON"
DECISION_TOO_LATE = "DECISION_TOO_LATE"
CLOSING_OUTSIDE_WINDOW = "CLOSING_OUTSIDE_WINDOW"
CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW = "CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW"
CLOSING_POST_KICKOFF = "CLOSING_POST_KICKOFF"
KICKOFF_UNREADABLE = "KICKOFF_UNREADABLE"
PHASE_NOT_USED = "PHASE_NOT_USED"


@dataclass(frozen=True)
class Verdict:
    """Admissibilité d'une observation à la preuve de maturité, et sa raison."""

    admissible: bool
    raison: str
    lead_time: timedelta | None
    #: Avance sur le DERNIER coup d'envoi connu. Renseignée seulement quand un
    #: calendrier a été fourni ; c'est elle qui expose la dérive à l'audit.
    lead_time_final: timedelta | None = None

    @property
    def lead_minutes(self) -> float | None:
        return None if self.lead_time is None else self.lead_time.total_seconds() / 60


def evaluate(observation, calendrier: HistoriqueHoraires | None = None) -> Verdict:
    """Cette observation respecte-t-elle le protocole de collecte courant ?

    Une observation refusée reste dans l'historique et reste auditable. Seule son
    admissibilité à la PREUVE change — sa phase, son horodatage et son identité
    ne sont jamais réécrits.

    Sans `calendrier`, le jugement porte uniquement sur ce que l'observation
    savait d'elle-même. Avec, une clôture est de surcroît confrontée au dernier
    coup d'envoi connu de sa rencontre.
    """
    kickoff = kickoff_de(observation.event_id)
    if kickoff is None:
        return Verdict(False, KICKOFF_UNREADABLE, None)

    lead = kickoff - observation.observed_at

    if observation.phase is ObservationPhase.DECISION:
        if lead > HORIZON_DECISION:
            return Verdict(False, LEGACY_DECISION_HORIZON, lead)
        if lead <= FENETRE_CLOTURE:
            # Sous la fenêtre de clôture, le collecteur actuel n'écrirait pas une
            # décision mais une clôture. L'observation décrit donc autre chose
            # que ce que son étiquette annonce.
            return Verdict(False, DECISION_TOO_LATE, lead)
        return Verdict(True, ELIGIBLE, lead)

    if observation.phase is ObservationPhase.CLOSING:
        # D'abord ce que l'observation savait au moment de la capture : ces deux
        # refus-là nomment une capture déjà fautive à l'instant T.
        if lead < timedelta(0):
            return Verdict(False, CLOSING_POST_KICKOFF, lead)
        if lead > FENETRE_CLOTURE:
            return Verdict(False, CLOSING_OUTSIDE_WINDOW, lead)

        # Puis, si l'historique des horaires est connu, ce que le match a fait
        # ENSUITE. La capture était honnête ; elle a simplement cessé de mesurer
        # une clôture.
        avance_finale = _avance_sur_horaire_final(observation, calendrier)
        if avance_finale is not None and not (
            timedelta(0) < avance_finale <= FENETRE_CLOTURE
        ):
            return Verdict(False, CLOSING_OUTSIDE_FINAL_SCHEDULE_WINDOW,
                           lead, avance_finale)

        return Verdict(True, ELIGIBLE, lead, avance_finale)

    # OPEN / INTERMEDIATE ne participent à aucune paire : les déclarer inadmissibles
    # n'exclut rien, cela nomme seulement ce qui était déjà vrai.
    return Verdict(False, PHASE_NOT_USED, lead)


def _avance_sur_horaire_final(observation,
                              calendrier: HistoriqueHoraires | None) -> timedelta | None:
    """Avance de l'observation sur le dernier coup d'envoi connu de sa rencontre.

    `None` quand aucun calendrier n'est fourni ou que la rencontre n'y figure
    pas : dans le doute, on ne refuse rien — un refus doit reposer sur une
    mesure, pas sur une absence d'information.
    """
    if calendrier is None:
        return None
    final = calendrier.dernier(stable_event_id(observation))
    return None if final is None else final - observation.observed_at


def eligible(observations, calendrier: HistoriqueHoraires | None = None) -> list:
    """Les seules observations admissibles à la preuve de maturité.

    À défaut de `calendrier`, il est reconstruit sur l'assiette fournie. C'est
    correct tant que cette assiette contient TOUS les horaires annoncés de chaque
    rencontre qu'elle mentionne — un sous-ensemble amputé du dernier report
    ferait passer un horaire intermédiaire pour le final, et RÉADMETTRAIT une
    clôture périmée. Un appelant qui filtre avant d'appeler doit donc passer le
    calendrier de l'historique complet.
    """
    calendrier = calendrier or historique_horaires(observations)
    return [o for o in observations if evaluate(o, calendrier).admissible]


def exclusions(observations,
               calendrier: HistoriqueHoraires | None = None) -> dict[str, int]:
    """Motifs de refus et leur compte — jamais un total muet."""
    calendrier = calendrier or historique_horaires(observations)
    motifs: dict[str, int] = {}
    for observation in observations:
        verdict = evaluate(observation, calendrier)
        if not verdict.admissible:
            motifs[verdict.raison] = motifs.get(verdict.raison, 0) + 1
    return motifs
