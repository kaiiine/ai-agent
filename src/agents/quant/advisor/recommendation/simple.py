"""Sizing V1 d'une ligne SINGLE (ADR-ADV-007) + assemblage du portefeuille à une
ligne. Le Lot 8 réutilisera `compute_single_stake`, sans la remplacer.

Kelly sur la probabilité PRUDENTE (`probability_low`, imposé par le contrat) ;
atténué par `fractional_kelly` (config) × `reliability` × `data_quality` ; borné
par les seuls plafonds présents (un `None` n'est jamais un plafond à 0)."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal

from ..domain.candidates import CandidateBet, CandidateEvaluation
from ..domain.enums import LineType
from ..domain.money import ONE, ZERO
from ..domain.portfolios import BetLeg, PortfolioLine, RecommendationPortfolio
from ..domain.requests import RecommendationRequest
from . import explanation

# Précision de CALCUL déterministe pour les divisions. Pas un arrondi métier
# (granularité de mise -> Lot 8 / ADR-ADV-002). Le cap `max_payout/odds` arrondit
# vers le BAS pour garantir `stake·odds <= max_payout` (jamais dépassé).
_DIV = Context(prec=28)
_DIV_FLOOR = Context(prec=28, rounding=ROUND_DOWN)

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "advisor" / "sizing_policy.json"
)


@dataclass(frozen=True)
class SizingProfile:
    fractional_kelly: Decimal
    per_line_cap_fraction: Decimal


def load_sizing_profiles(path: pathlib.Path = _CONFIG_PATH) -> Mapping[str, SizingProfile]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: SizingProfile(
            fractional_kelly=Decimal(p["fractional_kelly"]),
            per_line_cap_fraction=Decimal(p["per_line_cap_fraction"]),
        )
        for name, p in data["profiles"].items()
    }


def kelly_fraction(probability_low: Decimal, bookmaker_odds: Decimal) -> Decimal:
    """`f* = (p·odds − 1)/(odds − 1)` sur la borne basse. <= 0 -> 0 (aucun edge
    prudent -> aucune mise, jamais une mise de compensation)."""
    numerator = probability_low * bookmaker_odds - ONE     # = expected_value_low
    if numerator <= ZERO:
        return ZERO
    return _DIV.divide(numerator, bookmaker_odds - ONE)


def compute_single_stake(
    candidate: CandidateBet, *, reliability: Decimal, bankroll: Decimal,
    max_total_stake: Decimal | None, sizing: SizingProfile,
) -> Decimal:
    """Mise d'une ligne SINGLE. `0` si non-SUPPORTED (BE-FR-011) ou Kelly <= 0."""
    if candidate.model_maturity != "SUPPORTED":
        return ZERO                                        # jamais de mise sur non-SUPPORTED
    kelly = kelly_fraction(candidate.probability_low, candidate.bookmaker_odds)
    if kelly <= ZERO:
        return ZERO

    raw_fraction = sizing.fractional_kelly * kelly * reliability * candidate.data_quality
    proposed = bankroll * raw_fraction

    # Plafonds : uniquement les présents (un None n'entre JAMAIS comme borne 0).
    caps = [proposed, bankroll, sizing.per_line_cap_fraction * bankroll]
    if max_total_stake is not None:
        caps.append(max_total_stake)
    if candidate.max_stake is not None:
        caps.append(candidate.max_stake)
    if candidate.max_payout is not None:
        caps.append(_DIV_FLOOR.divide(candidate.max_payout, candidate.bookmaker_odds))

    stake = min(caps)
    return stake if stake > ZERO else ZERO


def build_single_portfolio(
    top: CandidateEvaluation, stake: Decimal, request: RecommendationRequest,
) -> RecommendationPortfolio:
    c = top.candidate
    line_id = f"line:{c.candidate_id}"
    leg = BetLeg(candidate_id=c.candidate_id, event_id=c.event_id, market_id=c.market_id,
                 selection=c.selection, bookmaker=c.bookmaker, odds=c.bookmaker_odds)
    line = PortfolioLine(
        line_id=line_id, line_type=LineType.SINGLE, bookmaker=c.bookmaker, legs=(leg,),
        stake=stake, total_odds=c.bookmaker_odds, estimated_probability=c.fair_probability,
        expected_value=c.expected_value_mean, worst_case_ev=c.expected_value_low,
        correlation_warning=None)

    target = request.target_total_odds
    target_match = target is not None and target.minimum <= c.bookmaker_odds <= target.maximum
    return RecommendationPortfolio(
        portfolio_id=f"pf:{c.candidate_id}", request_id=request.request_id,
        strategy_id=request.ranking_profile, lines=(line,),
        total_stake=stake, unallocated_bankroll=request.bankroll - stake,
        expected_return=c.expected_value_mean, expected_profit=stake * c.expected_value_mean,
        downside_score=c.expected_value_low, concentration_score=ZERO,  # ligne unique (multi-lignes = Lot 8)
        target_odds_match=target_match, quality_score=c.data_quality, warnings=(),
        explanation=explanation.build_single_explanation(top, stake))
