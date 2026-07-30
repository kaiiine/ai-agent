"""Outil d'évaluation de maturité : exécute le walk-forward RÉEL, agrège les
observations hors échantillon, et produit un `ModelSupportDecision` MÉCANIQUE.

C'est le « rapport de readiness » du cas B (données insuffisantes) : il rend la
promotion future une simple conséquence de nouvelles données, pas un nouveau
chantier. Aucune métrique n'est fabriquée ; la CLV vient de l'`odds_history`
réel (vide -> NOT_YET_MEASURABLE) ; la freshness live est déclarée par l'appelant
(non wirée au point de décision -> NOT_MEASURABLE).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .calibration import metrics
from .calibration.walk_forward import WalkForwardRun, build_metrics, run_walk_forward
from .clv import OddsObservation, clv_readiness
from .maturity import (
    FRESHNESS_MEASURABLE,
    FRESHNESS_NOT_MEASURABLE,
    MaturityObservations,
    MaturityPolicy,
    ModelSupportDecision,
    evaluate_maturity,
    load_maturity_policy,
)


@dataclass(frozen=True)
class MaturityAssessment:
    decision: ModelSupportDecision
    run: WalkForwardRun
    metrics: dict
    observations: MaturityObservations


def _per_fold_brier(run: WalkForwardRun) -> dict[str, float]:
    groups: dict[str, list] = defaultdict(list)
    for (probs, outcome), kickoff in zip(run.model_predictions, run.fold_kickoffs):
        groups[kickoff[:7]].append((probs, outcome))     # regroupe par mois "YYYY-MM"
    return {month: metrics.evaluate(preds)["brier"]["value"] for month, preds in groups.items()}


def assess_one_x_two_maturity(
    *,
    matches,
    model,
    league_id: str,
    season: str,
    odds_observations: Sequence[OddsObservation] = (),
    live_freshness_status: str = FRESHNESS_NOT_MEASURABLE,
    policy: MaturityPolicy | None = None,
) -> MaturityAssessment:
    policy = policy or load_maturity_policy()
    run = run_walk_forward(matches, model, league_id, season)
    m = build_metrics(run)

    fold_briers = _per_fold_brier(run)
    fold_spread = (max(fold_briers.values()) - min(fold_briers.values())) if len(fold_briers) >= 2 else None
    raw_ece = m["calibration"]["raw"]["ece"]["ece"]
    best_baseline = min(
        m["baselines"]["uniform"]["brier"]["value"],
        m["baselines"]["prior_frequency"]["brier"]["value"],
    )
    coverage = (run.n_evaluated / run.n_total) if run.n_total else None
    mean_dq = (sum(run.data_qualities) / len(run.data_qualities)) if run.data_qualities else None

    readiness = clv_readiness(list(odds_observations))

    observations = MaturityObservations(
        n_evaluated=run.n_evaluated,
        n_temporal_folds=m["temporal_folds"]["n_folds"],
        calibration_error=raw_ece,
        model_brier=m["model"]["brier"]["value"],
        best_baseline_brier=best_baseline,
        data_coverage=round(coverage, 4) if coverage is not None else None,
        mean_data_quality=round(mean_dq, 4) if mean_dq is not None else None,
        fold_brier_spread=round(fold_spread, 4) if fold_spread is not None else None,
        clv_status=readiness.status,
        clv_mean=readiness.mean_clv,                     # Decimal ou None — jamais 0
        live_freshness_status=live_freshness_status,
    )
    decision = evaluate_maturity(
        model_name=model.model_name,
        model_version=model.model_version,
        observations=observations,
        policy=policy,
    )
    return MaturityAssessment(decision=decision, run=run, metrics=m, observations=observations)


def assess_default_one_x_two(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Évaluation sur le dataset réel embarqué (Ligue 1 2025-26). Rapport de readiness
    reproductible : charge la fixture réelle, exécute le walk-forward, verdict mécanique."""
    from src.agents.quant.gateway.core.identity_data import TEAMS
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
    from .calibration.historical_dataset import FL1_LEAGUE_ID, FL1_SEASON, load_fl1_2025
    from .sports.football.market_models.one_x_two import OneXTwoModel

    resolver = IdentityResolver(TEAMS)
    matches, _fingerprint, _n_finished = load_fl1_2025(resolver)
    return assess_one_x_two_maturity(
        matches=matches, model=OneXTwoModel(),
        league_id=FL1_LEAGUE_ID, season=FL1_SEASON,
        odds_observations=odds_observations,
        # La fraîcheur live est désormais CÂBLÉE (Gateway.data_freshness ->
        # gateway_staleness_probe -> evaluate_live_event) et testée : le chemin de
        # décision expose une fraîcheur mesurée -> capacité MEASURABLE. Distinct de
        # la CLV, qui reste NOT_YET_MEASURABLE faute de DONNÉES collectées.
        live_freshness_status=FRESHNESS_MEASURABLE,
    )
