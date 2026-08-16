"""Capture des prédictions au moment du scan — le seul moment où elles existent.

Une cote se re-télécharge, une prédiction non : elle n'existe qu'à l'instant où le
modèle l'a produite. C'est pourquoi cette capture est branchée DANS le scan, là où
la collecte CLV est hors-bande (`axon clv-collect`).

ÉCHANTILLON : tous les candidats ÉVALUÉS, pas seulement ceux affichés. Ne garder
que les mieux classés mesurerait la calibration du modèle sur ses seules
convictions fortes — un échantillon choisi par le résultat qu'on veut mesurer.

Ne lève jamais : un échec de comptabilité ne doit pas casser un scan.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .record import PredictionRecord
from .store import JsonlPredictionStore


class _ShimIdentite:
    """Objet minimal accepté par `clv.identity.stable_event_id` (duck-typing).

    Réutilise la convention d'identité prouvée sur le store réel plutôt que d'en
    inventer une seconde : l'identifiant bookmaker quand il existe, l'identité
    canonique sinon.
    """

    __slots__ = ("event_id", "source_event_id", "bookmaker")

    def __init__(self, event_id: str, source_event_id: str | None, bookmaker: str):
        self.event_id = event_id
        self.source_event_id = source_event_id
        self.bookmaker = bookmaker


def _identite(candidat, source_event_id: str | None) -> str:
    from src.agents.quant.betting_engine.clv.identity import stable_event_id

    return stable_event_id(_ShimIdentite(
        candidat.event_id, source_event_id, candidat.bookmaker))


def capturer_predictions(evaluations, *, decided_at: datetime,
                         adapted_for=None, store=None, run_id=None) -> int:
    """Écrit une prédiction par candidat évalué. Rend le nombre écrit.

    `adapted_for(candidat)` sert uniquement à récupérer l'identifiant bookmaker,
    qui rend l'identité insensible aux reports d'horaire ; son absence dégrade
    l'identité sans faire échouer la capture (même repli que la CLV).
    """
    store = store or JsonlPredictionStore()
    ecrites = 0
    for evaluation in evaluations:
        candidat = getattr(evaluation, "candidate", evaluation)
        try:
            adapte = adapted_for(candidat) if adapted_for is not None else None
            # Une prédiction postérieure au coup d'envoi n'en est pas une : le
            # record le refuse, et c'est bien ce qu'on veut — pas de silence.
            store.append(PredictionRecord(
                stable_event_id=_identite(
                    candidat, getattr(adapte, "source_event_id", None)),
                market_type=candidat.market_type,
                selection=candidat.selection,
                participant_ids=tuple(candidat.participant_ids),
                model_version=candidat.model_version,
                fair_probability=Decimal(candidat.fair_probability),
                bookmaker_odds=(None if candidat.bookmaker_odds is None
                                else Decimal(candidat.bookmaker_odds)),
                bookmaker=candidat.bookmaker,
                scheduled_at=candidat.scheduled_at,
                decided_at=decided_at,
                run_id=run_id))
            ecrites += 1
        except Exception:   # noqa: BLE001 — jamais au prix du scan
            continue
    return ecrites
