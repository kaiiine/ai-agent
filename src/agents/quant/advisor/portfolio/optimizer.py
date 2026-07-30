"""Optimiseur de portefeuilles (Lot 8, PRD §13 ; combos ADR-ADV-014). Produit un
portefeuille PRIMAIRE (glouton depuis le classement canonique) + des ALTERNATIVES
exploratoires ancrées, dédupliquées et ordonnées de façon stable.

Clé d'ordre (ADR/current-state §10.5) : le primaire reste toujours en tête ;
les alternatives sont ordonnées par RANG DE L'ANCRE (position au ranking), tie-break
final lexical. Aucun agrégat n'est érigé en fonction objectif. Heuristique V1.

COMBOS : alloués UNIQUEMENT dans le portefeuille PRIMAIRE, APRÈS tous les singles,
dans le même budget et le même suivi d'exposition (jamais un remplacement de single).
Les alternatives restent strictement SINGLE (comportement inchangé). Un combo consomme
le budget UNE fois et compte son stake sur CHAQUE jambe (exposition/concentration)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from ..combos.builder import ComboEvaluation
from ..combos.sizing import combo_sizing_profile
from ..domain.candidates import CandidateEvaluation
from ..domain.enums import LineType
from ..domain.money import ZERO
from ..domain.portfolios import (
    BetLeg, PortfolioExplanation, PortfolioLine, RecommendationPortfolio,
)
from ..domain.requests import RecommendationRequest
from ..recommendation.simple import SizingProfile
from .allocation import Allocation, allocate_lines
from .constraints import PortfolioCaps

_CORRELATION_WARNING = (
    "INDEPENDENT_ENOUGH : proxy STRUCTUREL (événements/participants disjoints), PAS "
    "une preuve d'indépendance ; corrélation résiduelle possible")


def _single_fact(al) -> dict:
    c = al.evaluation.candidate
    leg = BetLeg(c.candidate_id, c.event_id, c.market_id, c.selection, c.bookmaker, c.bookmaker_odds)
    line = PortfolioLine(
        line_id=f"line:{c.candidate_id}", line_type=LineType.SINGLE, bookmaker=c.bookmaker,
        legs=(leg,), stake=al.stake, total_odds=c.bookmaker_odds,
        estimated_probability=c.fair_probability, expected_value=c.expected_value_mean,
        worst_case_ev=c.expected_value_low, correlation_warning=None)
    return {"line": line, "stake": al.stake, "ev_mean": c.expected_value_mean,
            "ev_low": c.expected_value_low, "quality": c.data_quality, "events": (c.event_id,),
            "select": ("classé ELIGIBLE", f"ranking_score={al.evaluation.ranking_score}"),
            "alloc": ("fractional Kelly prudent (Lot 6) sous caps d'exposition",
                      "arrondi vers le bas à la granularité")}


def _combo_fact(cl) -> dict:
    combo = cl.combo
    pricing = combo.pricing
    legs = tuple(
        BetLeg(l.candidate.candidate_id, l.candidate.event_id, l.candidate.market_id,
               l.candidate.selection, l.candidate.bookmaker, l.candidate.bookmaker_odds)
        for l in combo.legs)
    line = PortfolioLine(
        line_id=f"line:{combo.combo_id}", line_type=LineType.COMBO,
        bookmaker=combo.legs[0].candidate.bookmaker, legs=legs, stake=cl.stake,
        total_odds=pricing.combined_odds, estimated_probability=pricing.combined_prob_mean,
        expected_value=pricing.expected_value, worst_case_ev=pricing.worst_case_ev,
        correlation_warning=_CORRELATION_WARNING)
    return {"line": line, "stake": cl.stake, "ev_mean": pricing.expected_value,
            "ev_low": pricing.worst_case_ev, "quality": combo.min_leg_quality,
            "events": tuple(l.candidate.event_id for l in combo.legs),
            "select": ("combo INDEPENDENT_ENOUGH admissible (Lot 9)", f"combo_id={combo.combo_id}"),
            "alloc": ("Kelly canonique sur borne basse combo (ADR-ADV-014)",
                      "exposition comptée sur chaque jambe ; arrondi vers le bas")}


def _facts(allocation: Allocation) -> list[dict]:
    return ([_single_fact(al) for al in allocation.lines]
            + [_combo_fact(cl) for cl in allocation.combo_lines])


def _dedup_key(allocation: Allocation):
    singles = tuple(sorted((al.evaluation.candidate.candidate_id, str(al.stake)) for al in allocation.lines))
    combos = tuple(sorted((cl.combo.combo_id, str(cl.stake)) for cl in allocation.combo_lines))
    return (singles, combos)


def _order_key(allocation: Allocation):
    ids = ([al.evaluation.candidate.candidate_id for al in allocation.lines]
           + [cl.combo.combo_id for cl in allocation.combo_lines])
    return tuple(sorted(ids))


def _build_portfolio(
    allocation: Allocation, request: RecommendationRequest, idx: int,
) -> RecommendationPortfolio:
    facts = _facts(allocation)
    total_stake = sum((f["stake"] for f in facts), ZERO)
    portfolio_lines = tuple(f["line"] for f in facts)
    selection_reasons = {f["line"].line_id: f["select"] for f in facts}
    allocation_reasons = {f["line"].line_id: f["alloc"] for f in facts}

    # Concentration : le stake d'un combo compte sur CHACUN de ses événements.
    by_event: dict[str, Decimal] = {}
    for f in facts:
        for ev in f["events"]:
            by_event[ev] = by_event.get(ev, ZERO) + f["stake"]
    concentration = max(by_event.values()) / total_stake

    expected_profit = sum((f["stake"] * f["ev_mean"] for f in facts), ZERO)
    downside = sum((f["stake"] * f["ev_low"] for f in facts), ZERO)
    quality = sum((f["stake"] * f["quality"] for f in facts), ZERO)

    # target_odds_match : valide UNIQUEMENT pour une ligne unique (single OU combo).
    target = request.target_total_odds
    target_match = (len(facts) == 1 and target is not None
                    and target.minimum <= facts[0]["line"].total_odds <= target.maximum)

    n_singles = len(allocation.lines)
    n_combos = len(allocation.combo_lines)
    dropped_all = list(allocation.dropped) + list(allocation.combo_dropped)
    explanation = PortfolioExplanation(
        summary=f"{n_singles} simple(s) + {n_combos} combo(s) — portefeuille "
                f"{'primaire' if idx == 0 else 'alternatif'}.",
        selection_reasons=selection_reasons, allocation_reasons=allocation_reasons,
        rejected_alternatives=tuple(f"{cid}:{reason}" for cid, reason in dropped_all),
        major_risks=("corrélation résiduelle des combos (INDEPENDENT_ENOUGH structurel)",
                     "liquidité non exposée en V1"),
        model_limitations=(
            "allocation gloutonne séquentielle (heuristique V1, jamais un optimum global) ; "
            "combos alloués après les singles, dans le portefeuille primaire uniquement",))

    return RecommendationPortfolio(
        portfolio_id=f"pf:{idx}:{_order_key(allocation)[0]}", request_id=request.request_id,
        strategy_id=request.ranking_profile, lines=portfolio_lines,
        total_stake=total_stake, unallocated_bankroll=request.bankroll - total_stake,
        expected_return=expected_profit / total_stake, expected_profit=expected_profit,
        downside_score=downside / total_stake, concentration_score=concentration,
        target_odds_match=target_match, quality_score=quality / total_stake,
        warnings=(), explanation=explanation)


def build_portfolios(
    ranked: Sequence[CandidateEvaluation], request: RecommendationRequest, *,
    sizing_profiles: Mapping[str, SizingProfile], caps_config: Mapping[str, PortfolioCaps],
    combos: Sequence[ComboEvaluation] = (),
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
    combo_sizing = combo_sizing_profile(sizing) if combos else None

    # PRIMAIRE : singles + combos (combos après les singles). Les ALTERNATIVES restent
    # strictement SINGLE (combos=None) -> comportement historique inchangé.
    primary = allocate_lines(ranked, request, sizing=sizing, caps=caps, bankroll=bankroll,
                             combos=list(combos), combo_sizing=combo_sizing)
    if primary is None or (not primary.lines and not primary.combo_lines):
        return ()                                          # aucune ligne allouable

    seen = {_dedup_key(primary)}
    alternatives: list[tuple[int, Allocation]] = []
    for rank_idx, ev in enumerate(ranked):
        alt = allocate_lines(ranked, request, sizing=sizing, caps=caps, bankroll=bankroll,
                             anchor_id=ev.candidate.candidate_id)
        if alt is None or not alt.lines:
            continue                                       # ancre non allouable -> alternative absente
        dedup = _dedup_key(alt)
        if dedup in seen:
            continue                                       # identique -> dédupliquée
        seen.add(dedup)
        alternatives.append((rank_idx, alt))

    alternatives.sort(key=lambda item: (item[0], _order_key(item[1])))
    chosen = ([primary] + [alloc for _, alloc in alternatives])[:request.max_portfolios]
    return tuple(_build_portfolio(alloc, request, idx) for idx, alloc in enumerate(chosen))
