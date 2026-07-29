"""Suivi de l'exposition par clé (PRD §13.4, ADR-ADV-008). Caps par événement /
participant / compétition / bookmaker, en PART de bankroll. `market:*` n'est pas
plafonné. Séquentiel : le cap restant dépend de ce qui est déjà alloué."""

from __future__ import annotations

from decimal import Decimal

from ..domain.candidates import CandidateBet
from ..domain.money import ZERO
from .constraints import PortfolioCaps

# Préfixe de clé d'exposition -> attribut de fraction plafond (market:* non plafonné).
_PREFIX_FRACTION = {
    "event": "max_event_exposure_fraction",
    "participant": "max_participant_exposure_fraction",
    "competition": "max_competition_exposure_fraction",
    "bookmaker": "max_bookmaker_exposure_fraction",
}


class ExposureTracker:
    def __init__(self):
        self._allocated: dict[str, Decimal] = {}

    def remaining_cap(self, candidate: CandidateBet, caps: PortfolioCaps, bankroll: Decimal) -> Decimal:
        """Cap d'exposition restant le plus contraignant parmi les clés plafonnées
        du candidat (min). Peut être <= 0 (dimension déjà saturée)."""
        remaining: Decimal | None = None
        for key in candidate.exposure_keys:
            attr = _PREFIX_FRACTION.get(key.split(":", 1)[0])
            if attr is None:
                continue
            cap = getattr(caps, attr) * bankroll
            rem = cap - self._allocated.get(key, ZERO)
            remaining = rem if remaining is None else min(remaining, rem)
        return remaining if remaining is not None else bankroll

    def allocate(self, candidate: CandidateBet, stake: Decimal) -> None:
        for key in candidate.exposure_keys:
            self._allocated[key] = self._allocated.get(key, ZERO) + stake
