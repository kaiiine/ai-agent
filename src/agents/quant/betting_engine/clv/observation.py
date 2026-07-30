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
        """Identité stable du marché pour apparier décision et clôture."""
        return (self.event_id, self.market_type, self.selection, self.bookmaker)
