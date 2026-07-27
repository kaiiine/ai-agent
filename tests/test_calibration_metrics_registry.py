"""Métriques + registre d'expériences (framework calibration). Synthétique."""

from __future__ import annotations

import math

import pytest

from src.agents.quant.betting_engine.calibration import metrics
from src.agents.quant.betting_engine.calibration.experiment_registry import (
    ExperimentResult,
    append_experiment,
    dataset_fingerprint,
    load_experiments,
    new_experiment_id,
)

_H = {"home": 1.0, "draw": 0.0, "away": 0.0}
_U = {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}


# ── Métriques ─────────────────────────────────────────────────────────────────
def test_brier_perfect_is_zero_and_uniform_is_two_thirds():
    assert metrics.brier_score(_H, "home") == 0.0
    assert abs(metrics.brier_score(_U, "home") - 2 / 3) < 1e-9   # (2/3)² + (1/3)² + (1/3)²


def test_log_loss_perfect_zero_uniform_ln3_and_clips_zero():
    # p=1 clippée à 1-eps -> ~1e-15 (≈0, pas exactement : clipping symétrique correct)
    assert metrics.log_loss(_H, "home") < 1e-9
    assert abs(metrics.log_loss(_U, "home") - math.log(3)) < 1e-9
    # proba 0 sur l'issue réelle -> clippée, jamais -inf
    clipped = metrics.log_loss({"home": 0.0, "draw": 0.5, "away": 0.5}, "home")
    assert math.isfinite(clipped)
    assert abs(clipped - (-math.log(metrics.LOG_LOSS_CLIP_EPSILON))) < 1e-6


def test_evaluate_is_self_describing():
    m = metrics.evaluate([(_U, "home"), (_H, "home"), (_U, "away")])
    assert m["n_evaluated"] == 3
    assert m["outcome_distribution"] == {"home": 2, "draw": 0, "away": 1}
    assert m["brier"]["convention"] == "sum_over_classes"
    assert m["brier"]["range"] == [0, 2]
    assert m["log_loss"]["clip_epsilon"] == 1e-15
    assert m["log_loss"]["base"] == "e"
    assert set(m["brier_per_class"]) == {"home", "draw", "away"}


def test_uniform_baseline_brier_constant():
    m = metrics.uniform_baseline(["home", "draw", "away", "home"])
    assert abs(m["brier"]["value"] - 2 / 3) < 1e-6


def test_calibration_bins_count_three_points_per_event():
    binc = metrics.calibration_bin_counts([(_U, "home"), (_H, "away")], n_bins=10)
    assert sum(binc["counts"]) == 2 * 3          # 3 classes par événement
    assert binc["n_bins"] == 10


# ── Registre ──────────────────────────────────────────────────────────────────
def _result(status="COMPLETED", metrics_dict=None):
    return ExperimentResult(
        experiment_id=new_experiment_id(), model_name="one_x_two", model_version="dc.v0",
        code_revision="abc123", dataset_fingerprint="sha256:deadbeef",
        feature_schema_version="football-1.0",
        evaluation_start="2025-08-15T00:00:00Z", evaluation_end="2026-05-17T00:00:00Z",
        point_in_time_policy="strict_prior_only", window_strategy="expanding",
        parameters={"rho": -0.13, "shrinkage_k": 12, "home_advantage": 1.11},
        n_events_total=305, n_events_evaluated=296, n_events_excluded=9,
        exclusion_reasons={"no_prior_form": 9},
        metrics=metrics_dict or metrics.evaluate([(_U, "home")]),
        experiment_status=status,
    )


def test_append_only_and_roundtrip(tmp_path):
    path = tmp_path / "experiments.jsonl"
    append_experiment(_result(), path)
    append_experiment(_result(), path)
    loaded = load_experiments(path)
    assert len(loaded) == 2                       # append-only : 2 lignes, aucune écrasée
    assert loaded[0]["model_name"] == "one_x_two"


def test_conventions_are_persisted_in_the_record(tmp_path):
    # Exigence explicite : convention Brier + clipping log loss DANS l'enregistrement.
    path = tmp_path / "e.jsonl"
    append_experiment(_result(), path)
    rec = load_experiments(path)[0]
    assert rec["metrics"]["brier"]["convention"] == "sum_over_classes"
    assert rec["metrics"]["log_loss"]["clip_epsilon"] == 1e-15
    assert rec["point_in_time_policy"] == "strict_prior_only"
    assert rec["window_strategy"] == "expanding"
    assert rec["parameters"]["rho"] == -0.13


def test_supported_status_is_forbidden():
    with pytest.raises(ValueError):
        _result(status="SUPPORTED")


def test_candidate_for_review_is_allowed():
    assert _result(status="CANDIDATE_FOR_REVIEW").experiment_status == "CANDIDATE_FOR_REVIEW"


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        _result(status="WHATEVER")


def test_dataset_fingerprint_deterministic():
    assert dataset_fingerprint(b"abc") == dataset_fingerprint(b"abc")
    assert dataset_fingerprint(b"abc") != dataset_fingerprint(b"abd")
    assert dataset_fingerprint(b"abc").startswith("sha256:")
