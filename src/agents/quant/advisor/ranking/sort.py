"""Classement glouton séquentiel (ADR-ADV-005 D5/D6) — ne classe QUE les
`ELIGIBLE` (les REVIEW_ONLY/REJECTED sont ignorés ici, cf. Lot 6).

Le `base_score` est indépendant de l'ordre d'entrée ; la sélection gloutonne
applique le `concentration_penalty` vis-à-vis des déjà-retenus, départage par
§12.4 (dont `candidate_id` lexical en dernier ressort → ordre TOTAL) : le
classement est donc strictement identique quel que soit l'ordre d'entrée."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from ..domain.candidates import CandidateEvaluation
from ..domain.enums import CandidateStatus
from . import components, explanation
from .profiles import RankingProfile
from .scorer import score_base


@dataclass(frozen=True)
class RankingResult:
    ranked: tuple[CandidateEvaluation, ...]        # ELIGIBLE classés (score + décomposition)
    non_rankable: tuple[CandidateEvaluation, ...]  # ELIGIBLE -> REJECTED (input REQUIRED absent)


@dataclass(frozen=True)
class _Scored:
    evaluation: CandidateEvaluation
    base_score: Decimal
    base_components: dict[str, Decimal]


def rank(
    evaluations: Sequence[CandidateEvaluation], *, profile: RankingProfile,
) -> RankingResult:
    scored: list[_Scored] = []
    non_rankable: list[CandidateEvaluation] = []

    for ev in evaluations:
        if ev.status is not CandidateStatus.ELIGIBLE:
            continue                                    # on ne classe QUE ELIGIBLE
        try:
            base = score_base(ev.candidate, profile)
        except components.NonRankable as exc:
            non_rankable.append(replace(
                ev, status=CandidateStatus.REJECTED, policy_reasons=(exc.reason_code,)))
            continue
        scored.append(_Scored(ev, base.base_score, base.components))

    ranked: list[CandidateEvaluation] = []
    retained_exposure: set[str] = set()
    remaining = list(scored)

    while remaining:
        best_item = None
        best_key = None
        best_conc = None
        best_effective = None
        for item in remaining:
            conc = components.concentration_penalty(
                item.evaluation.candidate.exposure_keys, retained_exposure, profile)
            effective = item.base_score - conc
            # Clé de sélection (le PLUS petit = meilleur) : score effectif desc,
            # puis tie-breakers §12.4 ; candidate_id lexical asc en dernier.
            key = (
                -effective,
                -item.evaluation.candidate.expected_value_low,
                -item.base_components["reliability_component"],
                -item.base_components["freshness_component"],
                conc,
                item.evaluation.candidate.candidate_id,
            )
            if best_key is None or key < best_key:
                best_key, best_item, best_conc, best_effective = key, item, conc, effective

        comps = explanation.ranking_components(
            best_item.base_components, best_item.base_score, best_conc, best_effective)
        ranked.append(replace(
            best_item.evaluation, ranking_score=best_effective, ranking_components=comps))
        retained_exposure |= set(best_item.evaluation.candidate.exposure_keys)
        remaining.remove(best_item)

    return RankingResult(ranked=tuple(ranked), non_rankable=tuple(non_rankable))
