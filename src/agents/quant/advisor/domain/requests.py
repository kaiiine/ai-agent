"""RecommendationRequest + OddsRange (PRD §8.1, §8.2) — avec invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .enums import MaturityPolicy, RiskProfile
from .money import ONE, require_decimal


@dataclass(frozen=True)
class OddsRange:
    minimum: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        require_decimal(self.minimum, "OddsRange.minimum")
        require_decimal(self.maximum, "OddsRange.maximum")
        if self.minimum <= ONE:
            raise ValueError(f"OddsRange.minimum doit être > 1 (cote), reçu {self.minimum}")
        if self.minimum > self.maximum:
            raise ValueError(f"OddsRange : minimum ({self.minimum}) > maximum ({self.maximum})")


@dataclass(frozen=True)
class RecommendationRequest:
    request_id: str
    decision_time: datetime
    bankroll: Decimal
    currency: str

    allowed_sports: frozenset[str] | None
    allowed_competitions: frozenset[str] | None
    allowed_bookmakers: frozenset[str] | None
    allowed_market_types: frozenset[str] | None

    target_total_odds: OddsRange | None
    max_total_stake: Decimal | None
    max_selections: int
    max_portfolios: int

    allow_singles: bool
    allow_combos: bool
    max_combo_legs: int

    risk_profile: RiskProfile
    maturity_policy: MaturityPolicy
    ranking_profile: str


    excluded_event_ids: frozenset[str]
    excluded_participant_ids: frozenset[str]
    excluded_market_types: frozenset[str]

    #: Ce que l'utilisateur a demandé : sûreté d'abord, ou rendement d'abord.
    #:
    #: PORTÉE JUSQU'ICI EXPRÈS. Le chemin de revue applique déjà cet ordre ; ce
    #: chemin-ci, celui de la MISE, est inatteignable tant qu'aucun modèle n'est
    #: SUPPORTED. Le jour où il le devient, il doit LIRE ce champ : sans lui, une
    #: demande « je veux du sûr » retomberait silencieusement sur « la meilleure
    #: espérance d'abord », et une sélection nettement moins probable pourrait
    #: remplacer une sélection nettement plus sûre au seul motif de son EV.
    #:
    #: Rien ici ne touche encore à Kelly, aux mises ni aux seuils : le champ est
    #: transporté, pas appliqué.
    posture: str = "SAFETY_FIRST"

    def __post_init__(self) -> None:
        require_decimal(self.bankroll, "bankroll")
        if self.bankroll <= 0:
            raise ValueError(f"bankroll doit être > 0, reçu {self.bankroll}")
        if self.max_total_stake is not None:
            require_decimal(self.max_total_stake, "max_total_stake")
            if self.max_total_stake > self.bankroll:
                raise ValueError("max_total_stake doit être <= bankroll")
        if self.max_selections < 1:
            raise ValueError("max_selections doit être >= 1")
        if self.max_portfolios < 1:
            raise ValueError("max_portfolios doit être >= 1")
        if self.allow_combos and self.max_combo_legs < 2:
            raise ValueError("max_combo_legs doit être >= 2 lorsque allow_combos=True")
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time doit être timezone-aware (explicite)")
        if not isinstance(self.risk_profile, RiskProfile):
            raise TypeError(f"risk_profile doit être un RiskProfile, reçu {type(self.risk_profile).__name__}")
        if not isinstance(self.maturity_policy, MaturityPolicy):
            raise TypeError("maturity_policy doit être un MaturityPolicy")
