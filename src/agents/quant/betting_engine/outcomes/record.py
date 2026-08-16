"""Prédiction horodatée, puis son issue réelle — la boucle qui manquait.

Le moteur prédisait sans que rien ne lui revienne. `OddsObservation` enregistre le
MOUVEMENT de la cote (CLV), jamais si le pari a gagné ; l'audit Advisor archive la
décision, jamais le résultat. Aucun `settle` n'existait nulle part : la seule mesure
de justesse venait d'un walk-forward historique, rejoué sur un CSV figé.

Ce module enregistre le couple (probabilité annoncée, issue observée). C'est le
minimum pour répondre à « ce modèle a-t-il raison en production ? » — question à
laquelle ni la CLV ni l'audit ne peuvent répondre.

Decimal partout, jamais float : même discipline que la frontière Advisor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Issue(str, Enum):
    """Issue observée pour la SÉLECTION enregistrée, jamais pour le match."""

    GAGNEE = "GAGNEE"
    PERDUE = "PERDUE"
    ANNULEE = "ANNULEE"          # walkover, forfait avant match : ni gagnée ni perdue


@dataclass(frozen=True)
class PredictionRecord:
    """Ce que le modèle a annoncé, à l'instant où il l'a annoncé.

    `stable_event_id` vient de `clv.identity` : il survit à un report d'horaire,
    sans quoi un match repoussé se réglerait comme un événement inconnu.
    """

    stable_event_id: str
    market_type: str
    selection: str
    participant_ids: tuple[str, ...]

    model_version: str
    fair_probability: Decimal        # probabilité ANNONCÉE pour cette sélection
    bookmaker_odds: Decimal | None   # None si la sélection n'était pas cotée
    bookmaker: str | None

    scheduled_at: datetime           # coup d'envoi annoncé à la décision
    decided_at: datetime             # instant de la prédiction
    run_id: str | None = None

    # Rempli au règlement, jamais à l'écriture.
    issue: Issue | None = None
    settled_at: datetime | None = None
    settlement_source: str | None = None

    def __post_init__(self) -> None:
        for nom in ("fair_probability", "bookmaker_odds"):
            valeur = getattr(self, nom)
            if valeur is not None and not isinstance(valeur, Decimal):
                raise TypeError(f"{nom} doit être Decimal (jamais float) — donnée sensible")
        if not (Decimal("0") <= self.fair_probability <= Decimal("1")):
            raise ValueError(f"fair_probability hors [0,1] : {self.fair_probability}")
        for nom in ("scheduled_at", "decided_at"):
            if getattr(self, nom).tzinfo is None:
                raise ValueError(f"{nom} doit être timezone-aware (ordre temporel prouvable)")
        # Une prédiction postérieure au coup d'envoi n'est plus une prédiction.
        if self.decided_at > self.scheduled_at:
            raise ValueError(
                f"decided_at ({self.decided_at}) postérieur au coup d'envoi "
                f"({self.scheduled_at}) : ce ne serait pas une prédiction")
        if (self.issue is None) != (self.settled_at is None):
            raise ValueError("issue et settled_at vont ensemble : réglé ou pas réglé")

    @property
    def est_reglee(self) -> bool:
        return self.issue is not None

    @property
    def compte_pour_la_calibration(self) -> bool:
        """Une sélection annulée n'a pas d'issue : la compter fausserait le score."""
        return self.issue in (Issue.GAGNEE, Issue.PERDUE)

    @property
    def realise(self) -> Decimal | None:
        """1 si la sélection est sortie, 0 sinon — le `y` du score de Brier."""
        if not self.compte_pour_la_calibration:
            return None
        return Decimal("1") if self.issue is Issue.GAGNEE else Decimal("0")

    def regler(self, issue: Issue, *, at: datetime, source: str) -> "PredictionRecord":
        """Rend une COPIE réglée. Jamais de mutation : le store est append-only,
        et une prédiction déjà réglée ne doit pas pouvoir changer d'issue."""
        if self.est_reglee:
            raise ValueError(
                f"déjà réglée ({self.issue.value}) : une issue ne se réécrit pas")
        if at.tzinfo is None:
            raise ValueError("settled_at doit être timezone-aware")
        if at < self.scheduled_at:
            raise ValueError(
                f"règlement ({at}) antérieur au coup d'envoi ({self.scheduled_at})")
        return replace(self, issue=issue, settled_at=at, settlement_source=source)

    @property
    def cle(self) -> tuple[str, str, str]:
        """Identité d'une prédiction : même rencontre, même marché, même sélection."""
        return (self.stable_event_id, self.market_type, self.selection)
