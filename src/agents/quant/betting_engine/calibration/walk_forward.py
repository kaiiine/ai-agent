"""Rejeu chronologique point-in-time (expanding), à paramètres FIXES.

Pour CHAQUE match, dans l'ordre chronologique :
  1. un `PointInTimeGateway` est construit avec `cutoff = kickoff` du match — il ne
     voit QUE les matchs strictement antérieurs (gate non-fuite, unité 1) ;
  2. `build_event_feature_set(..., gateway=pit, as_of=cutoff)` reconstruit les
     features sans fuite ;
  3. le modèle prédit ; un match sans forme antérieure (journée 1) sort en
     INSUFFICIENT_DATA -> exclu, aucune probabilité fabriquée.

Aucun paramètre du modèle n'est réestimé (rho/shrinkage/home_advantage figés) :
c'est un rejeu, pas un entraînement. Le harness ne touche jamais le statut du
modèle et ne produit jamais SUPPORTED (au mieux CANDIDATE_FOR_REVIEW).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch
from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent, CanonicalParticipant
from src.agents.quant.betting_engine.core.market_model import DataReadiness
from src.agents.quant.betting_engine.sports.football.feature_engineering import build_event_feature_set
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel
from src.agents.quant.betting_engine.calibration import metrics
from src.agents.quant.betting_engine.calibration.experiment_registry import (
    ExperimentResult,
    new_experiment_id,
)
from src.agents.quant.betting_engine.calibration.point_in_time_gateway import PointInTimeGateway

_CLASSES = ("home", "draw", "away")


def outcome_of(match: CanonicalMatch) -> str:
    if match.goals_home > match.goals_away:
        return "home"
    if match.goals_away > match.goals_home:
        return "away"
    return "draw"


@dataclass(frozen=True)
class WalkForwardRun:
    model_predictions: list[tuple[dict, str]]      # (probas modèle, issue réelle)
    frequency_baseline: list[tuple[dict, str]]     # (fréquences point-in-time, issue réelle)
    n_total: int
    n_evaluated: int
    exclusions: dict                               # {raison: compte}
    evaluation_start: str
    evaluation_end: str


def run_walk_forward(
    matches: Sequence[CanonicalMatch],
    model: OneXTwoModel,
    league_id: str,
    season: str,
) -> WalkForwardRun:
    ordered = sorted(matches, key=lambda m: m.kickoff)
    model_predictions: list[tuple[dict, str]] = []
    frequency_baseline: list[tuple[dict, str]] = []
    exclusions: Counter = Counter()

    for match in ordered:
        cutoff = match.kickoff
        actual = outcome_of(match)

        # Gate non-fuite : le gateway ne voit que kickoff < cutoff (STRICT).
        pit = PointInTimeGateway(matches, cutoff=cutoff, league_id=league_id, season=season)
        event = CanonicalEvent(
            event_id=match.canonical_match_id, sport="football", competition_id=league_id,
            participants=(CanonicalParticipant(match.home_team_id, "home"),
                          CanonicalParticipant(match.away_team_id, "away")),
            scheduled_at=cutoff,
        )
        features = build_event_feature_set(event, gateway=pit, as_of=cutoff)

        if model.assess_data_readiness(event, features) == DataReadiness.INSUFFICIENT_DATA:
            exclusions["INSUFFICIENT_DATA_no_prior_form"] += 1
            continue

        preds = model.predict_selections(event, features, point_in_time=cutoff)
        probs = {c: preds[c].fair_probability for c in _CLASSES}
        model_predictions.append((probs, actual))

        # Baseline fréquences POINT-IN-TIME (issues des matchs strictement antérieurs).
        prior = [outcome_of(x) for x in matches if x.kickoff < cutoff]
        if prior:
            counts = Counter(prior)
            freq = {c: counts.get(c, 0) / len(prior) for c in _CLASSES}
            frequency_baseline.append((freq, actual))

    return WalkForwardRun(
        model_predictions=model_predictions,
        frequency_baseline=frequency_baseline,
        n_total=len(ordered),
        n_evaluated=len(model_predictions),
        exclusions=dict(exclusions),
        evaluation_start=ordered[0].kickoff.isoformat() if ordered else "",
        evaluation_end=ordered[-1].kickoff.isoformat() if ordered else "",
    )


def build_metrics(run: WalkForwardRun) -> dict:
    """Métriques modèle + baselines (uniforme, fréquences point-in-time)."""
    model_metrics = metrics.evaluate(run.model_predictions)
    outcomes = [o for _, o in run.model_predictions]
    return {
        "model": model_metrics,
        "baselines": {
            "uniform": metrics.uniform_baseline(outcomes),
            "prior_frequency": metrics.evaluate(run.frequency_baseline),
        },
        "calibration_bins": metrics.calibration_bin_counts(run.model_predictions),
        "beats_uniform_brier": model_metrics["brier"]["value"]
        < metrics.uniform_baseline(outcomes)["brier"]["value"],
    }


def build_experiment_result(
    run: WalkForwardRun,
    model: OneXTwoModel,
    dataset_fingerprint: str,
    code_revision: str,
    feature_schema_version: str = "football-1.0",
) -> ExperimentResult:
    """Assemble un `ExperimentResult`. JAMAIS `SUPPORTED`. Aucune mutation du
    manifest ni du statut du modèle : un résultat n'est pas une décision de support.

    Le statut reflète la VALIDITÉ de l'expérience, PAS sa performance : un run
    valide (≥1 événement évalué) est disponible pour examen humain
    (`CANDIDATE_FOR_REVIEW`) qu'il batte OU PERDE contre les baselines — les
    métriques parlent d'elles-mêmes, jamais un statut dégradé automatique.
    """
    from src.agents.quant.dixon_coles import (
        AWAY_FACTOR, DECAY, DEFAULT_RHO, DEFAULT_SHRINKAGE_K, HOME_ADVANTAGE, LEAGUE_AVG_GOALS,
    )

    computed = build_metrics(run)
    # VALIDITÉ, pas performance : indépendant du fait de battre les baselines.
    status = "CANDIDATE_FOR_REVIEW" if run.n_evaluated > 0 else "FAILED"

    return ExperimentResult(
        experiment_id=new_experiment_id(),
        model_name="one_x_two",
        model_version=model.model_version,
        code_revision=code_revision,
        dataset_fingerprint=dataset_fingerprint,
        feature_schema_version=feature_schema_version,
        evaluation_start=run.evaluation_start,
        evaluation_end=run.evaluation_end,
        point_in_time_policy="strict_prior_only",
        window_strategy="expanding",
        parameters={
            "rho": DEFAULT_RHO, "shrinkage_k": DEFAULT_SHRINKAGE_K,
            "home_advantage": HOME_ADVANTAGE, "away_factor": AWAY_FACTOR,
            "league_avg_goals": LEAGUE_AVG_GOALS, "decay": DECAY,
        },
        n_events_total=run.n_total,
        n_events_evaluated=run.n_evaluated,
        n_events_excluded=run.n_total - run.n_evaluated,
        exclusion_reasons=run.exclusions,
        metrics=computed,
        experiment_status=status,
    )
