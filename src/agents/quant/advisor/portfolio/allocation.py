"""Allocation gloutonne séquentielle d'un portefeuille multi-single (Lot 8).

Réutilise la primitive de sizing SINGLE (`compute_single_stake`, Lot 6) — jamais
une 2ᵉ formule. Ordre IMPÉRATIF par ligne (ADR-ADV-002/007) :
  compute_single_stake -> caps budget/exposition -> montant admissible
  -> round DOWN (granularité) -> stake > 0 ? -> stake >= min_line_stake ?
  -> ligne créée OU écartée. Jamais d'arrondi avant les caps.

Heuristique séquentielle/gloutonne (V1) : le résultat dépend de l'ordre de
passage (rang du classement, ou ancre en tête), jamais un optimum global."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..combos.builder import ComboEvaluation
from ..combos.sizing import build_combo_candidate, combo_reliability
from ..domain.candidates import CandidateEvaluation
from ..domain.money import ZERO
from ..domain.requests import RecommendationRequest
from ..policy.reason_codes import CORRELATED_SAME_ORIGIN
from ..recommendation.simple import SizingProfile, compute_single_stake
from .bankroll import Budget
from .constraints import PortfolioCaps
from .exposure import ExposureTracker


@dataclass(frozen=True)
class AllocatedLine:
    evaluation: CandidateEvaluation
    stake: Decimal


@dataclass(frozen=True)
class AllocatedComboLine:
    combo: ComboEvaluation
    stake: Decimal


@dataclass(frozen=True)
class Allocation:
    lines: list[AllocatedLine]
    dropped: list[tuple[str, str]]         # (candidate_id, raison) — traçabilité (§15)
    combo_lines: list[AllocatedComboLine] = field(default_factory=list)
    combo_dropped: list[tuple[str, str]] = field(default_factory=list)   # (combo_id, raison)


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


def _combo_stake(
    combo: ComboEvaluation, request: RecommendationRequest, *, combo_sizing: SizingProfile,
    caps: PortfolioCaps, bankroll: Decimal, budget: Budget, exposure: ExposureTracker,
) -> tuple[Decimal, str | None]:
    """(stake, raison). Réutilise EXACTEMENT `compute_single_stake` (Kelly canonique)
    sur le CandidateBet synthétique du combo (borne basse, exposition unionnée)."""
    synth = build_combo_candidate(combo)                       # exposure_keys = union des jambes
    base = compute_single_stake(synth, reliability=combo_reliability(combo), bankroll=bankroll,
                                max_total_stake=request.max_total_stake, sizing=combo_sizing)
    admissible = min(base, budget.remaining(), exposure.remaining_cap(synth, caps, bankroll))
    stake = caps.round_down(admissible)
    if stake <= ZERO:
        return ZERO, "STAKE_NON_POSITIVE"
    if stake < caps.min_line_stake:
        return ZERO, "STAKE_BELOW_MIN"
    return stake, None


def allocate_lines(
    ranked: list[CandidateEvaluation], request: RecommendationRequest, *,
    sizing: SizingProfile, caps: PortfolioCaps, bankroll: Decimal, anchor_id: str | None = None,
    combos: list[ComboEvaluation] | None = None, combo_sizing: SizingProfile | None = None,
) -> Allocation | None:
    """Allocation (lignes créées + écartées tracées), ordre = ancre (si fournie)
    puis reste dans l'ordre du classement. Retourne `None` si l'ANCRE ne peut pas
    être allouée (alternative absente).

    Les COMBOS (si fournis) sont alloués APRÈS tous les singles, dans le MÊME budget
    et le MÊME suivi d'exposition : un combo ne remplace jamais un single et son stake
    compte sur CHAQUE jambe (exposition unionnée). Sans combos -> comportement SINGLE
    strictement inchangé."""
    budget = Budget(min(bankroll, request.max_total_stake) if request.max_total_stake is not None else bankroll)
    exposure = ExposureTracker()

    order = list(ranked)
    if anchor_id is not None:
        anchor = next(e for e in ranked if e.candidate.candidate_id == anchor_id)
        order = [anchor] + [e for e in ranked if e.candidate.candidate_id != anchor_id]

    lines: list[AllocatedLine] = []
    dropped: list[tuple[str, str]] = []
    #: (event_id, probability_origin) déjà servis. Règle conservatrice : au plus
    #: UNE sélection misée par distribution et par événement, tant qu'aucun modèle
    #: de dépendance n'est validé. Ce n'est pas une matrice de corrélation — c'en
    #: est le contraire : on refuse d'en fabriquer une, donc on ne cumule pas.
    origines_servies: set[tuple[str, str]] = set()
    for i, ev in enumerate(order):
        if len(lines) >= request.max_selections:               # respecte max_selections
            break
        origine = getattr(ev.candidate, "probability_origin", None)
        cle_origine = (ev.candidate.event_id, origine) if origine else None
        if cle_origine is not None and cle_origine in origines_servies:
            if anchor_id is not None and i == 0:
                return None                                    # l'ancre elle-même est corrélée
            dropped.append((ev.candidate.candidate_id, CORRELATED_SAME_ORIGIN))
            continue
        stake, reason = _line_stake(ev, request, sizing=sizing, caps=caps,
                                    bankroll=bankroll, budget=budget, exposure=exposure)
        if stake <= ZERO:
            if anchor_id is not None and i == 0:
                return None                                    # ancre échoue -> alternative absente
            dropped.append((ev.candidate.candidate_id, reason))
            continue
        budget.allocate(stake)
        exposure.allocate(ev.candidate, stake)
        if cle_origine is not None:
            origines_servies.add(cle_origine)
        lines.append(AllocatedLine(ev, stake))

    # COMBOS après les singles (mêmes budget + exposition). Ne remplacent jamais un single.
    combo_lines: list[AllocatedComboLine] = []
    combo_dropped: list[tuple[str, str]] = []
    if combos and combo_sizing is not None:
        for combo in combos:
            stake, reason = _combo_stake(combo, request, combo_sizing=combo_sizing, caps=caps,
                                         bankroll=bankroll, budget=budget, exposure=exposure)
            if stake <= ZERO:
                combo_dropped.append((combo.combo_id, reason))
                continue
            budget.allocate(stake)                             # consomme le budget UNE fois
            exposure.allocate(build_combo_candidate(combo), stake)   # exposition sur chaque jambe
            combo_lines.append(AllocatedComboLine(combo, stake))
    return Allocation(lines, dropped, combo_lines, combo_dropped)
