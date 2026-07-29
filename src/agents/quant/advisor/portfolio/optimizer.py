"""Optimiseur de portefeuilles multi-single (Lot 8, PRD §13). Produit un
portefeuille PRIMAIRE (glouton depuis le classement canonique) + des ALTERNATIVES
exploratoires ancrées, dédupliquées et ordonnées de façon stable.

Clé d'ordre (ADR/current-state §10.5) : le primaire reste toujours en tête ;
les alternatives sont ordonnées par RANG DE L'ANCRE (métrique fondée = position
au ranking), tie-break final lexical sur le tuple des candidate_id. Aucun agrégat
n'est érigé en fonction objectif. Heuristique V1, jamais un optimum global."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from ..domain.candidates import CandidateEvaluation
from ..domain.enums import LineType
from ..domain.money import ZERO
from ..domain.portfolios import (
    BetLeg, PortfolioExplanation, PortfolioLine, RecommendationPortfolio,
)
from ..domain.requests import RecommendationRequest
from ..recommendation.simple import SizingProfile
from .allocation import AllocatedLine, Allocation, allocate_lines
from .constraints import PortfolioCaps


def _dedup_key(lines: Sequence[AllocatedLine]):
    return tuple(sorted((al.evaluation.candidate.candidate_id, str(al.stake)) for al in lines))


def _order_key(lines: Sequence[AllocatedLine]):
    return tuple(sorted(al.evaluation.candidate.candidate_id for al in lines))


def _wsum(lines, attr) -> Decimal:
    return sum((al.stake * getattr(al.evaluation.candidate, attr) for al in lines), ZERO)


def _concentration_score(lines, total_stake: Decimal) -> Decimal:
    by_event: dict[str, Decimal] = {}
    for al in lines:
        by_event[al.evaluation.candidate.event_id] = (
            by_event.get(al.evaluation.candidate.event_id, ZERO) + al.stake)
    return max(by_event.values()) / total_stake       # part max sur un événement (single-line = 1)


def _build_portfolio(
    allocation: Allocation, request: RecommendationRequest, idx: int,
) -> RecommendationPortfolio:
    lines = allocation.lines
    total_stake = sum((al.stake for al in lines), ZERO)
    portfolio_lines = []
    selection_reasons, allocation_reasons = {}, {}
    for al in lines:
        c = al.evaluation.candidate
        line_id = f"line:{c.candidate_id}"
        leg = BetLeg(c.candidate_id, c.event_id, c.market_id, c.selection, c.bookmaker, c.bookmaker_odds)
        portfolio_lines.append(PortfolioLine(
            line_id=line_id, line_type=LineType.SINGLE, bookmaker=c.bookmaker, legs=(leg,),
            stake=al.stake, total_odds=c.bookmaker_odds, estimated_probability=c.fair_probability,
            expected_value=c.expected_value_mean, worst_case_ev=c.expected_value_low,
            correlation_warning=None))
        selection_reasons[line_id] = ("classé ELIGIBLE", f"ranking_score={al.evaluation.ranking_score}")
        allocation_reasons[line_id] = ("fractional Kelly prudent (Lot 6) sous caps d'exposition",
                                       "arrondi vers le bas à la granularité")

    # target_odds_match : valide UNIQUEMENT pour une ligne unique (pas de cote
    # totale pour des simples indépendants — current-state §10.5).
    target = request.target_total_odds
    target_match = (len(lines) == 1 and target is not None
                    and target.minimum <= lines[0].evaluation.candidate.bookmaker_odds <= target.maximum)

    explanation = PortfolioExplanation(
        summary=f"{len(lines)} pari(s) simple(s) — portefeuille {'primaire' if idx == 0 else 'alternatif'}.",
        selection_reasons=selection_reasons, allocation_reasons=allocation_reasons,
        rejected_alternatives=tuple(f"{cid}:{reason}" for cid, reason in allocation.dropped),
        major_risks=("simples indépendants (pas de cote totale)", "liquidité non exposée en V1"),
        model_limitations=(
            "allocation gloutonne séquentielle (heuristique V1, jamais un optimum global) ; "
            "combos = Lot 9",))

    return RecommendationPortfolio(
        portfolio_id=f"pf:{idx}:{_order_key(lines)[0]}", request_id=request.request_id,
        strategy_id=request.ranking_profile, lines=tuple(portfolio_lines),
        total_stake=total_stake, unallocated_bankroll=request.bankroll - total_stake,
        expected_return=_wsum(lines, "expected_value_mean") / total_stake,
        expected_profit=_wsum(lines, "expected_value_mean"),
        downside_score=_wsum(lines, "expected_value_low") / total_stake,
        concentration_score=_concentration_score(lines, total_stake),
        target_odds_match=target_match, quality_score=_wsum(lines, "data_quality") / total_stake,
        warnings=(), explanation=explanation)


def build_portfolios(
    ranked: Sequence[CandidateEvaluation], request: RecommendationRequest, *,
    sizing_profiles: Mapping[str, SizingProfile], caps_config: Mapping[str, PortfolioCaps],
) -> tuple[RecommendationPortfolio, ...]:
    ranked = list(ranked)
    if not ranked:
        return ()
    key = request.risk_profile.value
    sizing = sizing_profiles.get(key)
    caps = caps_config.get(key)
    if sizing is None or caps is None:
        raise ValueError(f"profil de sizing/caps non configuré : {key}")
    bankroll = request.bankroll

    primary = allocate_lines(ranked, request, sizing=sizing, caps=caps, bankroll=bankroll)
    if primary is None or not primary.lines:
        return ()                                          # aucune ligne allouable

    seen = {_dedup_key(primary.lines)}
    alternatives: list[tuple[int, Allocation]] = []
    for rank_idx, ev in enumerate(ranked):
        alt = allocate_lines(ranked, request, sizing=sizing, caps=caps, bankroll=bankroll,
                             anchor_id=ev.candidate.candidate_id)
        if alt is None or not alt.lines:
            continue                                       # ancre non allouable -> alternative absente
        dedup = _dedup_key(alt.lines)
        if dedup in seen:
            continue                                       # identique -> dédupliquée
        seen.add(dedup)
        alternatives.append((rank_idx, alt))

    alternatives.sort(key=lambda item: (item[0], _order_key(item[1].lines)))  # rang ancre asc, puis lexical
    chosen = ([primary] + [alloc for _, alloc in alternatives])[:request.max_portfolios]
    return tuple(_build_portfolio(alloc, request, idx) for idx, alloc in enumerate(chosen))
