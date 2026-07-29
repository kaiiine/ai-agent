"""Allocation gloutonne séquentielle d'un portefeuille multi-single (Lot 8).

Réutilise la primitive de sizing SINGLE (`compute_single_stake`, Lot 6) — jamais
une 2ᵉ formule. Ordre IMPÉRATIF par ligne (ADR-ADV-002/007) :
  compute_single_stake -> caps budget/exposition -> montant admissible
  -> round DOWN (granularité) -> stake > 0 ? -> stake >= min_line_stake ?
  -> ligne créée OU écartée. Jamais d'arrondi avant les caps.

Heuristique séquentielle/gloutonne (V1) : le résultat dépend de l'ordre de
passage (rang du classement, ou ancre en tête), jamais un optimum global."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..domain.candidates import CandidateEvaluation
from ..domain.money import ZERO
from ..domain.requests import RecommendationRequest
from ..recommendation.simple import SizingProfile, compute_single_stake
from .bankroll import Budget
from .constraints import PortfolioCaps
from .exposure import ExposureTracker


@dataclass(frozen=True)
class AllocatedLine:
    evaluation: CandidateEvaluation
    stake: Decimal


@dataclass(frozen=True)
class Allocation:
    lines: list[AllocatedLine]
    dropped: list[tuple[str, str]]         # (candidate_id, raison) — traçabilité (§15)


def _line_stake(
    ev: CandidateEvaluation, request: RecommendationRequest, *, sizing: SizingProfile,
    caps: PortfolioCaps, bankroll: Decimal, budget: Budget, exposure: ExposureTracker,
) -> tuple[Decimal, str | None]:
    """(stake, raison d'écart). stake == 0 <=> ligne écartée."""
    reliability = ev.ranking_components["reliability_component"]
    base = compute_single_stake(ev.candidate, reliability=reliability, bankroll=bankroll,
                                max_total_stake=request.max_total_stake, sizing=sizing)
    # Caps AVANT arrondi : budget restant + exposition la plus contraignante.
    admissible = min(base, budget.remaining(), exposure.remaining_cap(ev.candidate, caps, bankroll))
    stake = caps.round_down(admissible)                        # arrondi APRÈS les caps
    if stake <= ZERO:                                          # invariant indépendant de min_line_stake
        return ZERO, "STAKE_NON_POSITIVE"
    if stake < caps.min_line_stake:
        return ZERO, "STAKE_BELOW_MIN"
    return stake, None


def allocate_lines(
    ranked: list[CandidateEvaluation], request: RecommendationRequest, *,
    sizing: SizingProfile, caps: PortfolioCaps, bankroll: Decimal, anchor_id: str | None = None,
) -> Allocation | None:
    """Allocation (lignes créées + écartées tracées), ordre = ancre (si fournie)
    puis reste dans l'ordre du classement. Retourne `None` si l'ANCRE ne peut pas
    être allouée (alternative absente)."""
    budget = Budget(min(bankroll, request.max_total_stake) if request.max_total_stake is not None else bankroll)
    exposure = ExposureTracker()

    order = list(ranked)
    if anchor_id is not None:
        anchor = next(e for e in ranked if e.candidate.candidate_id == anchor_id)
        order = [anchor] + [e for e in ranked if e.candidate.candidate_id != anchor_id]

    lines: list[AllocatedLine] = []
    dropped: list[tuple[str, str]] = []
    for i, ev in enumerate(order):
        if len(lines) >= request.max_selections:               # respecte max_selections
            break
        stake, reason = _line_stake(ev, request, sizing=sizing, caps=caps,
                                    bankroll=bankroll, budget=budget, exposure=exposure)
        if stake <= ZERO:
            if anchor_id is not None and i == 0:
                return None                                    # ancre échoue -> alternative absente
            dropped.append((ev.candidate.candidate_id, reason))
            continue
        budget.allocate(stake)
        exposure.allocate(ev.candidate, stake)
        lines.append(AllocatedLine(ev, stake))
    return Allocation(lines, dropped)
