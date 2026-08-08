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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .collect import FENETRE_CLOTURE, HORIZON_DECISION
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
CLOSING_POST_KICKOFF = "CLOSING_POST_KICKOFF"
KICKOFF_UNREADABLE = "KICKOFF_UNREADABLE"
PHASE_NOT_USED = "PHASE_NOT_USED"

#: L'horodatage ISO à l'intérieur de l'identité d'événement. Il est extrait par
#: motif et NON par découpage sur « : » — l'identité vaut
#: `event:tennis:tour:2026-08-08T14:30:00Z:player_a=…`, et un `split(":")[3]`
#: rend « 2026-08-08T14 », soit une heure ronde plausible et fausse. L'erreur est
#: silencieuse : elle décale les temps d'avance de quelques dizaines de minutes
#: et fabrique des clôtures « postérieures au coup d'envoi » qui n'existent pas.
_HORODATAGE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")


def kickoff_de(event_id: str) -> datetime | None:
    """Coup d'envoi porté par l'identité canonique, ou `None` si illisible."""
    trouve = _HORODATAGE.search(event_id or "")
    if trouve is None:
        return None
    return datetime.fromisoformat(trouve.group(1).replace("Z", "+00:00"))


@dataclass(frozen=True)
class Verdict:
    """Admissibilité d'une observation à la preuve de maturité, et sa raison."""

    admissible: bool
    raison: str
    lead_time: timedelta | None

    @property
    def lead_minutes(self) -> float | None:
        return None if self.lead_time is None else self.lead_time.total_seconds() / 60


def evaluate(observation) -> Verdict:
    """Cette observation respecte-t-elle le protocole de collecte courant ?

    Une observation refusée reste dans l'historique et reste auditable. Seule son
    admissibilité à la PREUVE change.
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
        if lead < timedelta(0):
            return Verdict(False, CLOSING_POST_KICKOFF, lead)
        if lead > FENETRE_CLOTURE:
            return Verdict(False, CLOSING_OUTSIDE_WINDOW, lead)
        return Verdict(True, ELIGIBLE, lead)

    # OPEN / INTERMEDIATE ne participent à aucune paire : les déclarer inadmissibles
    # n'exclut rien, cela nomme seulement ce qui était déjà vrai.
    return Verdict(False, PHASE_NOT_USED, lead)


def eligible(observations) -> list:
    """Les seules observations admissibles à la preuve de maturité."""
    return [o for o in observations if evaluate(o).admissible]


def exclusions(observations) -> dict[str, int]:
    """Motifs de refus et leur compte — jamais un total muet."""
    motifs: dict[str, int] = {}
    for observation in observations:
        verdict = evaluate(observation)
        if not verdict.admissible:
            motifs[verdict.raison] = motifs.get(verdict.raison, 0) + 1
    return motifs
