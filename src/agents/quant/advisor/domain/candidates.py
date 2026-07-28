"""CandidateBet + CandidateEvaluation (PRD §8.5, §8.7) — avec invariants.

`fair_odds = 1 / fair_probability` : la vérification EXACTE (précision ADR-ADV-002)
est faite par le Candidate Generator (Lot 3) qui la calcule. Ici on valide les
bornes structurelles (voir §Hors-scope Lot 1).

`source_decision_id` est `str | None` (divergence v1) : le Betting Engine
n'expose pas encore d'identifiant de décision stable (cf. Q5 du Lot 0) ; il ne
sera JAMAIS inventé — résolu au Lot 2 (propagation d'un id réel ou dette).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .enums import CandidateStatus
from .money import ONE, ZERO, require_decimal, require_unit_interval


@dataclass(frozen=True)
class CandidateBet:
    candidate_id: str

    event_id: str
    sport: str
    competition_id: str
    scheduled_at: datetime

    bookmaker: str
    market_id: str
    market_type: str
    selection: str

    bookmaker_odds: Decimal
    fair_probability: Decimal
    probability_low: Decimal
    probability_high: Decimal
    fair_odds: Decimal
    implied_probability: Decimal

    expected_value_mean: Decimal
    expected_value_low: Decimal
    edge_mean: Decimal
    edge_low: Decimal

    model_version: str
    model_maturity: str
    calibration_score: Decimal | None
    data_quality: Decimal
    freshness_score: Decimal | None    # None = FRESHNESS_UNKNOWN (divergence v1, cf. Lot 0)
    liquidity_score: Decimal | None

    max_stake: Decimal | None
    max_payout: Decimal | None
    is_boosted: bool

    participant_ids: tuple[str, ...]
    exposure_keys: frozenset[str]

    warnings: tuple[str, ...]
    explanation_ref: str
    source_decision_id: str | None     # provenance ; jamais inventée (Q5)

    def __post_init__(self) -> None:
        # Montants/cotes : Decimal obligatoire (aucun float).
        for name in ("bookmaker_odds", "fair_probability", "probability_low",
                     "probability_high", "fair_odds", "implied_probability",
                     "expected_value_mean", "expected_value_low", "edge_mean", "edge_low"):
            require_decimal(getattr(self, name), name)

        # Bornes de probabilité (PRD §8.5).
        require_unit_interval(self.fair_probability, "fair_probability")
        require_unit_interval(self.implied_probability, "implied_probability")
        if not (ZERO <= self.probability_low <= self.fair_probability
                <= self.probability_high <= ONE):
            raise ValueError("invariant : 0 <= probability_low <= fair_probability "
                             "<= probability_high <= 1 violé")
        if self.bookmaker_odds <= ONE:
            raise ValueError(f"bookmaker_odds doit être > 1, reçu {self.bookmaker_odds}")
        if self.fair_odds < ONE:
            raise ValueError(f"fair_odds doit être >= 1, reçu {self.fair_odds}")

        # Scores normalisés dans [0, 1]. Un absent reste None (jamais 0 silencieux).
        require_unit_interval(self.data_quality, "data_quality")
        for name in ("calibration_score", "freshness_score", "liquidity_score"):
            value = getattr(self, name)
            if value is not None:
                require_unit_interval(value, name)

        for name in ("max_stake", "max_payout"):
            value = getattr(self, name)
            if value is not None:
                require_decimal(value, name)


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: CandidateBet
    status: CandidateStatus
    policy_reasons: tuple[str, ...]
    ranking_score: Decimal | None
    ranking_components: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not isinstance(self.status, CandidateStatus):
            raise TypeError("status doit être un CandidateStatus")
        if self.ranking_score is not None:
            require_decimal(self.ranking_score, "ranking_score")
        # Bornes/sémantique des composants : définies par ADR-ADV-005 (Lot 5),
        # pas ici — on valide seulement le typage Decimal.
        for key, value in self.ranking_components.items():
            require_decimal(value, f"ranking_components[{key}]")
