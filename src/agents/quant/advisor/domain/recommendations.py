"""RecommendationResponse (PRD §8.11) — réponse finale exposée à l'utilisateur."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from .candidates import CandidateEvaluation
from .enums import RecommendationOutcome
from .portfolios import RecommendationPortfolio


@dataclass(frozen=True)
class RecommendationResponse:
    request_id: str
    generated_at: datetime
    outcome: RecommendationOutcome
    portfolios: tuple[RecommendationPortfolio, ...]
    review_candidates: tuple[CandidateEvaluation, ...]
    rejection_summary: Mapping[str, int]
    warnings: tuple[str, ...]
    audit_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, RecommendationOutcome):
            raise TypeError("outcome doit être un RecommendationOutcome")
        # Cohérence outcome ↔ contenu (garde-fous PRD §8.11 / §11).
        if self.outcome is RecommendationOutcome.RECOMMENDED and not self.portfolios:
            raise ValueError("RECOMMENDED exige au moins un portefeuille")
        if self.outcome is RecommendationOutcome.REVIEW_CANDIDATES and not self.review_candidates:
            raise ValueError("REVIEW_CANDIDATES exige au moins un review_candidate")
        if self.outcome in (RecommendationOutcome.NO_OPPORTUNITY,
                            RecommendationOutcome.NO_EVALUABLE_EVENTS) and self.portfolios:
            raise ValueError(f"{self.outcome.value} ne doit porter aucun portefeuille")
