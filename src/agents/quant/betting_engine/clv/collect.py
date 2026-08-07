"""Collecte CLV AUTOMATIQUE — une commande, un planificateur, aucune décision humaine.

L'historique comptait 113 décisions et zéro clôture. La chaîne fonctionnait ; ce
qui manquait était l'exécution. Capturer une clôture demande d'être là JUSTE
AVANT le coup d'envoi, et les rencontres partent à toute heure : personne ne
lance une commande à 01:00 puis à 18:30 puis à 19:40.

Ce module retire le choix de la phase des mains de l'appelant. Elle se déduit du
seul fait qui compte — la distance au coup d'envoi :

    déjà commencée                  -> rien (ni décision ni clôture)
    coup d'envoi dans moins de W     -> CLÔTURE
    coup d'envoi au-delà de W        -> DÉCISION

Lancé toutes les quelques minutes, le collecteur traverse ainsi chaque rencontre
dans le bon ordre, sans qu'aucune horloge humaine n'intervienne.

IDEMPOTENCE. Un planificateur qui tourne toutes les cinq minutes ne doit pas
écrire cinq cents décisions pour un même match. Une observation n'est écrite que
si le couple (marché, phase) est absent de l'historique. Ce n'est pas seulement
de l'hygiène de fichier : l'appariement retient la PREMIÈRE clôture d'un marché,
si bien qu'une seconde capture serait au mieux ignorée, au pire trompeuse quant à
la taille réelle de l'échantillon.

Aucune cote n'est fabriquée : le collecteur ne fait que scanner et écrire ce que
le bookmaker expose, avec la provenance du scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Sequence

from .observation import ObservationPhase
from .recorder import record_odds

#: Fenêtre pendant laquelle une cote est considérée comme la CLÔTURE. Elle borne
#: l'erreur : une clôture prise au plus tôt à W minutes du coup d'envoi. Trop
#: large, elle capture une cote encore loin de la ligne finale ; trop étroite,
#: elle rate les rencontres si le planificateur tourne moins souvent qu'elle.
#: Trente minutes se marient avec un déclenchement toutes les cinq à dix minutes.
FENETRE_CLOTURE = timedelta(minutes=30)

#: Au-delà, une rencontre est trop lointaine pour qu'une décision ait du sens :
#: les marchés bougent encore beaucoup et la cote observée ne ressemble pas à
#: celle qu'on prendrait. Deux jours couvrent le cycle des demandes du produit.
HORIZON_DECISION = timedelta(days=2)


@dataclass(frozen=True)
class CollectSummary:
    """Ce que la passe a fait, phase par phase. Chaque nombre est un fait."""

    decisions_ecrites: int = 0
    clotures_ecrites: int = 0
    deja_connues: int = 0
    trop_lointaines: int = 0
    deja_commencees: int = 0
    non_exploitables: int = 0

    def describe(self) -> str:
        return (f"{self.decisions_ecrites} décision(s), {self.clotures_ecrites} clôture(s) "
                f"— {self.deja_connues} déjà connue(s), {self.trop_lointaines} trop "
                f"lointaine(s), {self.deja_commencees} déjà commencée(s), "
                f"{self.non_exploitables} non exploitable(s)")


def phase_pour(kickoff: datetime | None, maintenant: datetime, *,
               fenetre: timedelta = FENETRE_CLOTURE,
               horizon: timedelta = HORIZON_DECISION) -> ObservationPhase | None:
    """La phase que MÉRITE cette rencontre, ou None si elle n'en mérite aucune.

    Une rencontre sans horaire connu ne peut pas être située par rapport à son
    coup d'envoi : elle est écartée plutôt que rangée par défaut dans la phase la
    moins gênante.
    """
    if kickoff is None:
        return None
    if kickoff <= maintenant:
        return None                       # déjà commencée : plus rien à observer
    if kickoff - maintenant <= fenetre:
        return ObservationPhase.CLOSING
    if kickoff - maintenant > horizon:
        return None                       # trop lointaine pour une décision utile
    return ObservationPhase.DECISION


def _deja_vues(store) -> set[tuple]:
    """(marché, phase) déjà présents dans l'historique."""
    return {(obs.market_key, obs.phase) for obs in store.all()}


def collect(
    events: Sequence[Any], *, event_resolver, store, source: str,
    now: datetime | None = None,
    fenetre: timedelta = FENETRE_CLOTURE,
    horizon: timedelta = HORIZON_DECISION,
    run_id: str | None = None,
    enregistrer: Callable = record_odds,
) -> CollectSummary:
    """Range les événements par phase, puis écrit ce qui manque.

    Les deux phases sont enregistrées par le MÊME chemin que la collecte
    manuelle : la canonicalisation, le garde de clôture et la provenance sont
    ceux déjà éprouvés. Ce module décide QUAND, jamais COMMENT.
    """
    maintenant = now or datetime.now(timezone.utc)
    connues = _deja_vues(store)

    par_phase: dict[ObservationPhase, list] = {ObservationPhase.DECISION: [],
                                               ObservationPhase.CLOSING: []}
    trop_loin = commencees = 0
    for event in events:
        kickoff = getattr(event, "start_time", None)
        phase = phase_pour(kickoff, maintenant, fenetre=fenetre, horizon=horizon)
        if phase is None:
            if kickoff is not None and kickoff <= maintenant:
                commencees += 1
            else:
                trop_loin += 1
            continue
        par_phase[phase].append(event)

    ecrites = {ObservationPhase.DECISION: 0, ObservationPhase.CLOSING: 0}
    ignorees = non_exploitables = 0
    for phase, lot in par_phase.items():
        if not lot:
            continue
        filtre = _StoreFiltrant(store, connues)
        resume = enregistrer(lot, event_resolver=event_resolver, store=filtre,
                             phase=phase, source=source, run_id=run_id)
        # Le nombre d'écritures est compté par le FILTRE, pas par le recorder :
        # celui-ci compte ce qu'il a proposé, pas ce qui a été retenu.
        ecrites[phase] = filtre.ecrites
        ignorees += filtre.ignorees
        non_exploitables += resume.events_skipped
        commencees += getattr(resume, "events_started", 0)

    return CollectSummary(
        decisions_ecrites=ecrites[ObservationPhase.DECISION],
        clotures_ecrites=ecrites[ObservationPhase.CLOSING],
        deja_connues=ignorees,
        trop_lointaines=trop_loin,
        deja_commencees=commencees,
        non_exploitables=non_exploitables,
    )


class _StoreFiltrant:
    """Enveloppe qui laisse passer ce qui est NOUVEAU, et compte le reste.

    Le filtre vit ici plutôt que dans le recorder : celui-ci canonicalise et
    persiste, et n'a pas à connaître l'historique déjà écrit. L'idempotence est
    une propriété de la COLLECTE répétée, pas de l'enregistrement d'un scan.
    """

    def __init__(self, store, connues: set[tuple]):
        self._store = store
        self._connues = connues
        self.ecrites = 0
        self.ignorees = 0

    def append(self, obs) -> None:
        cle = (obs.market_key, obs.phase)
        if cle in self._connues:
            self.ignorees += 1
            return
        self._connues.add(cle)
        self._store.append(obs)
        self.ecrites += 1

    def all(self):
        return self._store.all()
