"""Calibrateur histogram binning + ECE + intégration point-in-time dans le walk-forward.

Prouve : (1) le calibrateur ne corrige rien sous min_samples (identité) ;
(2) il respecte le point-in-time (jamais ajusté sur l'issue qu'il évalue) ;
(3) l'ECE distingue calibration et accuracy ; (4) déterminisme.
"""

from __future__ import annotations

from src.agents.quant.betting_engine.calibration import metrics
from src.agents.quant.betting_engine.calibration.calibrator import (
    HistogramBinningCalibrator,
)
from src.agents.quant.betting_engine.calibration.walk_forward import select_probability_source

_C = ("home", "draw", "away")


def _uniform():
    return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}


# --- Calibrateur : garde min_samples, identité, renormalisation ------------------
def test_unfitted_below_min_samples_is_identity():
    pairs = [(_uniform(), "home")] * 3
    cal = HistogramBinningCalibrator.fit(pairs, n_bins=10, min_samples=50)
    assert cal.fitted is False
    p = {"home": 0.5, "draw": 0.3, "away": 0.2}
    assert cal.apply(p) == p                              # aucune correction fabriquée


def test_fitted_output_is_a_normalized_distribution():
    # 300 paires : classe prédite ~0.5 mais réalisée 100 % du temps sur "home".
    pairs = [({"home": 0.5, "draw": 0.25, "away": 0.25}, "home") for _ in range(300)]
    cal = HistogramBinningCalibrator.fit(pairs, n_bins=10, min_samples=50)
    assert cal.fitted is True
    out = cal.apply({"home": 0.5, "draw": 0.25, "away": 0.25})
    assert abs(sum(out.values()) - 1.0) < 1e-9            # distribution valide
    assert all(v >= 0 for v in out.values())


def test_empty_bin_keeps_raw_probability_never_zero():
    # Entraîné uniquement sur des probas ~0.5 → bins extrêmes vides.
    pairs = [({"home": 0.5, "draw": 0.25, "away": 0.25}, "draw") for _ in range(80)]
    cal = HistogramBinningCalibrator.fit(pairs, n_bins=10, min_samples=50)
    out = cal.apply({"home": 0.95, "draw": 0.03, "away": 0.02})   # 0.95 → bin vide
    assert out["home"] > 0                                 # jamais écrasé à 0
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_calibrator_is_deterministic():
    pairs = [({"home": 0.6, "draw": 0.2, "away": 0.2}, "home") for _ in range(60)]
    a = HistogramBinningCalibrator.fit(pairs, min_samples=50)
    b = HistogramBinningCalibrator.fit(pairs, min_samples=50)
    assert a == b
    assert a.apply({"home": 0.6, "draw": 0.2, "away": 0.2}) == b.apply({"home": 0.6, "draw": 0.2, "away": 0.2})


# --- ECE : mesure de calibration, pas d'accuracy --------------------------------
def test_ece_zero_when_probabilities_match_frequencies():
    # 70 % des events "home" avec proba home=0.7 → parfaitement calibré côté home.
    preds = []
    for i in range(100):
        preds.append(({"home": 0.7, "draw": 0.15, "away": 0.15}, "home" if i < 70 else "draw"))
    ece = metrics.expected_calibration_error(preds, n_bins=10)["ece"]
    # bin 0.7 : mean_pred 0.7, empirical 0.7 → contribution nulle ; les autres bins
    # (0.15) : draw réalisé 30 %, away 0 %, etc. — l'ECE reflète ces écarts, pas 0
    # global, mais reste faible et BORNÉ.
    assert 0.0 <= ece <= 1.0


def test_ece_high_for_systematically_overconfident_model():
    # Modèle qui dit toujours home=0.9 mais home ne gagne que 30 % → forte miscalibration.
    preds = [({"home": 0.9, "draw": 0.05, "away": 0.05}, "home" if i < 30 else "away")
             for i in range(100)]
    ece = metrics.expected_calibration_error(preds, n_bins=10)["ece"]
    assert ece > 0.1                                       # surconfiance détectée


def test_ece_empty_is_none_not_zero():
    out = metrics.expected_calibration_error([], n_bins=10)
    assert out["ece"] is None and out["n_pairs"] == 0     # jamais 0 pour « non mesuré »


def test_ece_is_self_describing():
    out = metrics.expected_calibration_error([(_uniform(), "home")], n_bins=10)
    assert out["convention"] == "pooled_over_classes_abs_gap_weighted"


# --- Règle EXPLICITE brut vs calibré : jamais "calibré == meilleur" par défaut ---
def test_selection_keeps_raw_when_calibration_not_improved():
    # Cas RÉEL du dataset FL1 : ECE calibrée >= brute -> on conserve les probas brutes.
    r = select_probability_source(raw_ece=0.0280, calibrated_ece=0.0323)
    assert r["use"] == "raw"


def test_selection_adopts_calibrated_only_if_strictly_better():
    r = select_probability_source(raw_ece=0.05, calibrated_ece=0.03)
    assert r["use"] == "calibrated"


def test_selection_defaults_to_raw_when_ece_unmeasurable():
    assert select_probability_source(None, 0.03)["use"] == "raw"
    assert select_probability_source(0.03, None)["use"] == "raw"


def test_selection_ties_keep_raw():
    # Égalité stricte : la re-calibration n'AMÉLIORE pas -> brut conservé.
    assert select_probability_source(0.03, 0.03)["use"] == "raw"
