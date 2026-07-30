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
from dataclasses import dataclass, field

from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch
from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent, CanonicalParticipant
from src.agents.quant.betting_engine.core.market_model import DataReadiness
from src.agents.quant.betting_engine.sports.football.feature_engineering import build_event_feature_set
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel
from src.agents.quant.betting_engine.calibration import metrics
from src.agents.quant.betting_engine.calibration.calibrator import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_N_BINS,
    HistogramBinningCalibrator,
)
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
    model_predictions: list[tuple[dict, str]]      # (probas modèle BRUTES, issue réelle)
    frequency_baseline: list[tuple[dict, str]]     # (fréquences point-in-time, issue réelle)
    n_total: int
    n_evaluated: int
    exclusions: dict                               # {raison: compte}
    evaluation_start: str
    evaluation_end: str
    # Prédictions RE-CALIBRÉES point-in-time (calibrateur ajusté à T uniquement sur
    # les matchs strictement antérieurs à T). Défaut vide : rétrocompat des runs
    # synthétiques construits à la main dans les tests.
    calibrated_predictions: list[tuple[dict, str]] = field(default_factory=list)
    calibrator_meta: dict = field(default_factory=dict)   # n_bins, min_samples, n_calibrated, n_identity
    fold_kickoffs: tuple[str, ...] = ()             # kickoff ISO de chaque prédiction évaluée (folds temporels)
    data_qualities: tuple[float, ...] = ()          # data_quality du modèle par prédiction évaluée


def run_walk_forward(
    matches: Sequence[CanonicalMatch],
    model: OneXTwoModel,
    league_id: str,
    season: str,
    *,
    calibrator_n_bins: int = DEFAULT_N_BINS,
    calibrator_min_samples: int = DEFAULT_MIN_SAMPLES,
) -> WalkForwardRun:
    ordered = sorted(matches, key=lambda m: m.kickoff)
    model_predictions: list[tuple[dict, str]] = []
    calibrated_predictions: list[tuple[dict, str]] = []
    frequency_baseline: list[tuple[dict, str]] = []
    fold_kickoffs: list[str] = []
    data_qualities: list[float] = []
    exclusions: Counter = Counter()

    # Historique (kickoff, probas brutes, issue) pour ajuster le calibrateur
    # point-in-time : à T, on ne fournit QUE les paires de kickoff < T (STRICT),
    # comme la gate features. Le calibrateur ne voit jamais l'issue qu'il corrige.
    calib_history: list[tuple[object, dict, str]] = []
    n_calibrated = 0

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
        fold_kickoffs.append(cutoff.isoformat())
        data_qualities.append(preds["home"].data_quality)   # identique aux 3 issues (même matrice)

        # Calibrateur point-in-time : ajusté STRICTEMENT sur les prédictions
        # antérieures (kickoff < cutoff), appliqué à la prédiction courante.
        prior_pairs = [(p, o) for (k, p, o) in calib_history if k < cutoff]
        calibrator = HistogramBinningCalibrator.fit(
            prior_pairs, n_bins=calibrator_n_bins, min_samples=calibrator_min_samples
        )
        calibrated_probs = calibrator.apply(probs)
        calibrated_predictions.append((calibrated_probs, actual))
        if calibrator.fitted:
            n_calibrated += 1
        calib_history.append((cutoff, probs, actual))

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
        calibrated_predictions=calibrated_predictions,
        calibrator_meta={
            "calibrator": "histogram_binning",
            "n_bins": calibrator_n_bins,
            "min_samples": calibrator_min_samples,
            "n_calibrated": n_calibrated,
            "n_identity": len(model_predictions) - n_calibrated,
        },
        fold_kickoffs=tuple(fold_kickoffs),
        data_qualities=tuple(data_qualities),
    )


def build_metrics(run: WalkForwardRun) -> dict:
    """Métriques modèle + baselines (uniforme, fréquences point-in-time) + calibration.

    La section `calibration` expose l'ECE AVANT (probas brutes) et APRÈS
    re-calibration point-in-time, plus le Brier/log-loss des probas re-calibrées —
    tout hors échantillon. Elle est purement additive : les clés historiques
    (`model`, `baselines`, `calibration_bins`, `beats_uniform_brier`) sont inchangées.
    """
    model_metrics = metrics.evaluate(run.model_predictions)
    outcomes = [o for _, o in run.model_predictions]
    calibrated_metrics = metrics.evaluate(run.calibrated_predictions) if run.calibrated_predictions else None
    raw_ece = metrics.expected_calibration_error(run.model_predictions)
    calibrated_ece = metrics.expected_calibration_error(run.calibrated_predictions)
    return {
        "model": model_metrics,
        "baselines": {
            "uniform": metrics.uniform_baseline(outcomes),
            "prior_frequency": metrics.evaluate(run.frequency_baseline),
        },
        "calibration_bins": metrics.calibration_bin_counts(run.model_predictions),
        "beats_uniform_brier": model_metrics["brier"]["value"]
        < metrics.uniform_baseline(outcomes)["brier"]["value"],
        "calibration": {
            "meta": run.calibrator_meta,
            "raw": {"ece": raw_ece},
            "point_in_time_calibrated": {
                "ece": calibrated_ece,
                "brier": calibrated_metrics["brier"] if calibrated_metrics else None,
                "log_loss": calibrated_metrics["log_loss"] if calibrated_metrics else None,
            },
            "recommendation": select_probability_source(raw_ece["ece"], calibrated_ece["ece"]),
        },
        "temporal_folds": _temporal_fold_summary(run),
    }


def select_probability_source(raw_ece: float | None, calibrated_ece: float | None) -> dict:
    """Règle EXPLICITE brut vs calibré (jamais « calibré == meilleur » par défaut).

    On n'adopte la re-calibration point-in-time que si elle AMÉLIORE STRICTEMENT
    l'ECE hors échantillon. Sinon, probabilités BRUTES conservées. Le calibrateur
    existe comme infrastructure, il n'est jamais appliqué aveuglément."""
    if raw_ece is None or calibrated_ece is None:
        return {"use": "raw", "reason": "ECE non mesurable -> probabilités brutes"}
    if calibrated_ece < raw_ece:
        return {"use": "calibrated",
                "reason": f"ECE calibrée {calibrated_ece} < brute {raw_ece} : re-calibration retenue"}
    return {"use": "raw",
            "reason": f"ECE calibrée {calibrated_ece} >= brute {raw_ece} : re-calibration NON retenue"}


def _temporal_fold_summary(run: WalkForwardRun, granularity: str = "month") -> dict:
    """Compte les FOLDS temporels réellement couverts par les prédictions évaluées.

    Un fold = un mois calendaire distinct (YYYY-MM) touché par une prédiction. Le
    walk-forward est expanding par-événement (granularité maximale) ; ce résumé
    répond à « combien de segments temporels distincts la validation couvre-t-elle »
    sans coder de période en dur — il dérive des kickoffs réels. Sert de mesure de
    stabilité temporelle pour la politique de maturité (jamais fabriqué)."""
    if granularity != "month":
        raise ValueError(f"granularité de fold non supportée : {granularity}")
    segments = sorted({k[:7] for k in run.fold_kickoffs})     # "YYYY-MM"
    return {"granularity": granularity, "n_folds": len(segments), "segments": segments}


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
            # Paramètres de MÉTHODE du calibrateur point-in-time (reproductibilité) —
            # distincts des seuils métier de promotion (ceux-là vivent en config).
            "calibrator": run.calibrator_meta.get("calibrator"),
            "calibrator_n_bins": run.calibrator_meta.get("n_bins"),
            "calibrator_min_samples": run.calibrator_meta.get("min_samples"),
        },
        n_events_total=run.n_total,
        n_events_evaluated=run.n_evaluated,
        n_events_excluded=run.n_total - run.n_evaluated,
        exclusion_reasons=run.exclusions,
        metrics=computed,
        experiment_status=status,
    )
