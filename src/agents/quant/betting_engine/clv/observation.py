"""Observation de cote horodatée pour l'`odds_history` (BE-FR-015 : « conserve les
cotes observées de l'ouverture à la clôture, en append-only »).

C'est la STRUCTURE DE COLLECTE minimale exigée pour rendre la CLV mesurable plus
tard : identité de marché + bookmaker + horodatage + cote + phase + provenance.
Aucune valeur de CLV n'est calculée ici tant qu'on n'a pas une paire
décision/clôture réelle (cf. clv.py). Les cotes sont des `Decimal` (jamais float :
donnée sensible à la précision, cohérent avec la frontière Advisor).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .identity import (
    scheduled_kickoff_as_observed,
    stable_event_id,
    stable_market_key,
)


class ObservationPhase(str, Enum):
    OPEN = "OPEN"                 # première cote observée (ouverture de marché)
    INTERMEDIATE = "INTERMEDIATE"
    DECISION = "DECISION"        # cote au moment de la décision / recommandation
    CLOSING = "CLOSING"          # cote de clôture (référence CLV)


@dataclass(frozen=True)
class OddsObservation:
    # --- Identité de marché (« même marché », « même sélection ») ---
    event_id: str                # canonical_event_id
    market_type: str
    selection: str               # canonique : home/draw/away/...
    bookmaker: str

    # --- Cote observée ---
    decimal_odds: Decimal
    observed_at: datetime
    phase: ObservationPhase

    # --- Provenance (attribuable à une source) ---
    source: str                  # ex. "winamax"
    source_event_id: str | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decimal_odds, Decimal):
            raise TypeError("decimal_odds doit être Decimal (jamais float) — donnée sensible")
        if self.decimal_odds <= Decimal("1"):
            raise ValueError(f"cote décimale invalide : {self.decimal_odds} (doit être > 1)")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at doit être timezone-aware (ordre temporel prouvable)")

    @property
    def market_key(self) -> tuple[str, str, str, str]:
        """« Ai-je déjà écrit cette observation ? » — clé d'IDEMPOTENCE du collecteur.

        Elle porte l'horaire, via `event_id`, et c'est indispensable : quand un
        match est repoussé, le collecteur doit pouvoir capturer une NOUVELLE
        clôture au voisinage du nouveau départ. Une clé insensible à l'horaire la
        rejetterait comme un doublon déjà connu.

        Pour rapprocher deux observations d'une même rencontre, c'est
        `stable_market_key` qu'il faut — voir `identity.py`.
        """
        return (self.event_id, self.market_type, self.selection, self.bookmaker)

    @property
    def scheduled_kickoff_as_observed(self) -> datetime | None:
        """Coup d'envoi tel qu'ANNONCÉ à l'instant de cette observation.

        Point-in-time : aucun report ultérieur ne la modifie, parce qu'elle est
        lue sur l'identité écrite dans le store au moment de la capture.
        """
        return scheduled_kickoff_as_observed(self)

    @property
    def stable_event_id(self) -> str:
        """Identité de la rencontre, insensible aux changements d'horaire."""
        return stable_event_id(self)

    @property
    def stable_market_key(self) -> tuple[str, str, str, str]:
        """« Même marché de la même rencontre » — clé d'APPARIEMENT de la CLV."""
        return stable_market_key(self)
