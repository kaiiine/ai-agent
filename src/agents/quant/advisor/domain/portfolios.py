"""BetLeg, PortfolioLine, PortfolioExplanation, RecommendationPortfolio (PRD §8.8–8.10, §15.1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from .enums import LineType
from .money import CENT, ONE, ZERO, require_decimal


@dataclass(frozen=True)
class BetLeg:
    candidate_id: str
    event_id: str
    market_id: str
    selection: str
    bookmaker: str
    odds: Decimal

    def __post_init__(self) -> None:
        require_decimal(self.odds, "BetLeg.odds")
        if self.odds <= ONE:
            raise ValueError(f"BetLeg.odds doit être > 1, reçu {self.odds}")


@dataclass(frozen=True)
class PortfolioLine:
    line_id: str
    line_type: LineType
    bookmaker: str
    legs: tuple[BetLeg, ...]
    stake: Decimal
    total_odds: Decimal
    estimated_probability: Decimal
    expected_value: Decimal
    worst_case_ev: Decimal
    correlation_warning: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.line_type, LineType):
            raise TypeError("line_type doit être un LineType")
        for name in ("stake", "total_odds", "estimated_probability", "expected_value", "worst_case_ev"):
            require_decimal(getattr(self, name), name)
        if not self.legs:
            raise ValueError("PortfolioLine doit avoir au moins un leg")
        if self.line_type is LineType.SINGLE and len(self.legs) != 1:
            raise ValueError("une ligne SINGLE a exactement un leg")
        if self.line_type is LineType.COMBO and len(self.legs) < 2:
            raise ValueError("une ligne COMBO a au moins deux legs")
        if self.stake < ZERO:
            raise ValueError("stake doit être >= 0")
        if self.total_odds <= ONE:
            raise ValueError("total_odds doit être > 1")
        if not (ZERO <= self.estimated_probability <= ONE):
            raise ValueError("estimated_probability doit être dans [0, 1]")
        # Tous les legs d'un combo partagent le même bookmaker (ADV-FR-017).
        if len({leg.bookmaker for leg in self.legs}) != 1:
            raise ValueError("tous les legs d'une ligne partagent un seul bookmaker (ADV-FR-017)")

    # Retour BRUT et profit NET sont deux nombres distincts : les confondre
    # présente une mise de 10 € à cote 1,5 comme un gain de 15 €. Ils vivent ici
    # et non dans le renderer, qui les dérivait lui-même — un montant affiché à
    # l'utilisateur ne doit avoir qu'une seule définition, et elle appartient au
    # domaine qui a décidé la mise.
    @property
    def gross_return(self) -> Decimal:
        """Ce que le bookmaker verse si la ligne passe, mise comprise."""
        return (self.stake * self.total_odds).quantize(CENT)

    @property
    def net_profit(self) -> Decimal:
        """Le gain, mise déduite."""
        return (self.gross_return - self.stake).quantize(CENT)


@dataclass(frozen=True)
class PortfolioExplanation:
    summary: str
    selection_reasons: Mapping[str, tuple[str, ...]]
    allocation_reasons: Mapping[str, tuple[str, ...]]
    rejected_alternatives: tuple[str, ...]
    major_risks: tuple[str, ...]
    model_limitations: tuple[str, ...]


@dataclass(frozen=True)
class RecommendationPortfolio:
    portfolio_id: str
    request_id: str
    strategy_id: str

    lines: tuple[PortfolioLine, ...]
    total_stake: Decimal
    unallocated_bankroll: Decimal

    expected_return: Decimal
    expected_profit: Decimal
    downside_score: Decimal
    concentration_score: Decimal

    target_odds_match: bool
    quality_score: Decimal
    warnings: tuple[str, ...]
    explanation: PortfolioExplanation

    def __post_init__(self) -> None:
        for name in ("total_stake", "unallocated_bankroll", "expected_return",
                     "expected_profit", "downside_score", "concentration_score", "quality_score"):
            require_decimal(getattr(self, name), name)
        if self.total_stake < ZERO or self.unallocated_bankroll < ZERO:
            raise ValueError("total_stake et unallocated_bankroll doivent être >= 0")
        if not isinstance(self.explanation, PortfolioExplanation):
            raise TypeError("explanation doit être un PortfolioExplanation")
