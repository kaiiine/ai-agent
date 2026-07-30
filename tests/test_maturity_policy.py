"""Politique de maturité : verdict MÉCANIQUE SUPPORTED/EXPERIMENTAL.

Prouve : (1) le verdict est déterministe et dérivé des critères ; (2) sur les
données RÉELLES le modèle reste honnêtement EXPERIMENTAL (jamais promu pour faire
passer le produit) ; (3) la gate PEUT promouvoir sur des preuves synthétiques
suffisantes (non truquée) ; (4) chaque blocage individuel empêche la promotion.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.agents.quant.betting_engine.assessment import assess_default_one_x_two
from src.agents.quant.betting_engine.maturity import (
    CLV_MEASURABLE,
    CLV_NOT_YET_MEASURABLE,
    FRESHNESS_MEASURABLE,
    FRESHNESS_NOT_MEASURABLE,
    MaturityObservations,
    Verdict,
    _CONFIG_PATH,
    _CHECKSUM_FIELDS,
    evaluate_maturity,
    load_maturity_policy,
)

_POLICY = load_maturity_policy()


def _passing_observations(**overrides) -> MaturityObservations:
    """Observations synthétiques qui satisfont TOUS les critères requis."""
    base = dict(
        n_evaluated=800,
        n_temporal_folds=6,
        calibration_error=0.02,
        model_brier=0.60,
        best_baseline_brier=0.66,
        data_coverage=0.95,
        mean_data_quality=0.9,
        fold_brier_spread=0.05,
        clv_status=CLV_MEASURABLE,
        clv_mean=0.012,
        live_freshness_status=FRESHNESS_MEASURABLE,
    )
    base.update(overrides)
    return MaturityObservations(**base)


def _decide(policy=_POLICY, **overrides):
    return evaluate_maturity(
        model_name="one_x_two", model_version="v0",
        observations=_passing_observations(**overrides), policy=policy,
    )


def _policy_with(*, required=None, criteria=None):
    kw = {}
    if required is not None:
        kw["required_for_support"] = {**_POLICY.required_for_support, **required}
    if criteria is not None:
        kw["criteria"] = {**_POLICY.criteria, **criteria}
    return replace(_POLICY, **kw)


# --- Config versionnée -----------------------------------------------------------
def test_policy_checksum_valid_and_tamper_evident(tmp_path):
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    data["criteria"]["min_sample_size"] = 1        # falsification sans recalcul checksum
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_maturity_policy(bad)


# --- Gate NON truquée : peut promouvoir sur preuves suffisantes -------------------
def test_sufficient_synthetic_evidence_is_supported():
    d = _decide()
    assert d.status == "SUPPORTED"
    assert all(c.verdict is Verdict.PASS for c in d.criteria if c.required)


def test_verdict_is_deterministic():
    a = _decide()
    b = _decide()
    assert a.status == b.status
    assert [c.verdict for c in a.criteria] == [c.verdict for c in b.criteria]


# --- Chaque blocage individuel empêche SUPPORTED ---------------------------------
def test_insufficient_sample_blocks_promotion():
    d = _decide(n_evaluated=100)
    assert d.status == "EXPERIMENTAL"
    assert any(c.name == "min_sample_size" and c.verdict is Verdict.FAIL for c in d.criteria)


def test_insufficient_calibration_blocks_promotion():
    d = _decide(calibration_error=0.20)
    assert d.status == "EXPERIMENTAL"
    assert any(c.name == "max_calibration_error" and c.verdict is Verdict.FAIL for c in d.criteria)


def test_insufficient_coverage_blocks_promotion():
    d = _decide(data_coverage=0.50)
    assert d.status == "EXPERIMENTAL"
    assert any(c.name == "min_data_coverage" and c.verdict is Verdict.FAIL for c in d.criteria)


def test_not_beating_baseline_blocks_promotion():
    d = _decide(model_brier=0.70, best_baseline_brier=0.66)   # modèle PIRE que baseline
    assert d.status == "EXPERIMENTAL"
    assert any(c.name == "must_beat_baselines" and c.verdict is Verdict.FAIL for c in d.criteria)


def test_unmeasurable_clv_blocks_promotion_and_is_not_zero():
    d = _decide(clv_status=CLV_NOT_YET_MEASURABLE, clv_mean=None)
    assert d.status == "EXPERIMENTAL"
    clv = next(c for c in d.criteria if c.name == "positive_clv")
    assert clv.verdict is Verdict.NOT_MEASURABLE
    assert clv.observed is None                     # jamais converti en 0


def test_unmeasurable_freshness_blocks_promotion():
    d = _decide(live_freshness_status=FRESHNESS_NOT_MEASURABLE)
    assert d.status == "EXPERIMENTAL"
    assert any(c.name == "measurable_live_freshness" and c.verdict is Verdict.NOT_MEASURABLE
               for c in d.criteria)


def test_measurable_but_negative_clv_fails_not_notmeasurable():
    d = _decide(clv_status=CLV_MEASURABLE, clv_mean=-0.03)
    clv = next(c for c in d.criteria if c.name == "positive_clv")
    assert clv.verdict is Verdict.FAIL              # mesurée et négative = FAIL, pas NOT_MEASURABLE
    assert d.status == "EXPERIMENTAL"


# --- Sémantique NOT_MEASURABLE : required_for_support gouverne le blocage --------
def test_required_not_measurable_blocks():
    # freshness REQUISE (défaut) + NOT_MEASURABLE -> bloque.
    d = _decide(live_freshness_status=FRESHNESS_NOT_MEASURABLE)
    assert d.status == "EXPERIMENTAL"
    fresh = next(c for c in d.criteria if c.name == "measurable_live_freshness")
    assert fresh.required is True and fresh.verdict is Verdict.NOT_MEASURABLE


def test_optional_not_measurable_does_not_block():
    # même critère rendu OPTIONNEL -> son NOT_MEASURABLE ne bloque plus.
    policy = _policy_with(required={"measurable_live_freshness": False})
    d = _decide(policy=policy, live_freshness_status=FRESHNESS_NOT_MEASURABLE)
    assert d.status == "SUPPORTED"                   # promu malgré freshness NOT_MEASURABLE (optionnelle)
    fresh = next(c for c in d.criteria if c.name == "measurable_live_freshness")
    assert fresh.required is False and fresh.verdict is Verdict.NOT_MEASURABLE  # reporté, non bloquant


def test_optional_fail_does_not_block():
    # un critère de MONITORING (required=False) qui ÉCHOUE ne bloque pas non plus.
    policy = _policy_with(required={"max_fold_brier_spread": False})
    d = _decide(policy=policy, fold_brier_spread=0.90)   # très mauvais, mais optionnel
    assert d.status == "SUPPORTED"
    spread = next(c for c in d.criteria if c.name == "max_fold_brier_spread")
    assert spread.required is False and spread.verdict is Verdict.FAIL


def test_no_not_measurable_all_pass_is_supported():
    # aucun NOT_MEASURABLE, tous requis PASS -> comportement inchangé (SUPPORTED).
    d = _decide()
    assert d.status == "SUPPORTED"
    assert all(c.verdict is Verdict.PASS for c in d.criteria if c.required)


def test_shipped_policy_has_clv_required_and_spread_monitoring():
    # Décisions V1 explicites dans la config livrée.
    assert _POLICY.is_required("positive_clv") is True             # CLV = prérequis réel (PRD DoD)
    assert _POLICY.is_required("measurable_live_freshness") is True
    assert _POLICY.is_required("max_fold_brier_spread") is False   # monitoring (single-season)


# --- Seuils lus depuis la config (aucun seuil implicite) ------------------------
def test_thresholds_come_from_config_not_hardcoded():
    assert _POLICY.criteria["min_sample_size"] == 500
    # borderline : 400 < 500 -> FAIL avec la politique livrée.
    assert _decide(n_evaluated=400).status == "EXPERIMENTAL"


def test_changing_a_config_threshold_changes_the_verdict():
    lax = _policy_with(criteria={"min_sample_size": 300})           # seuil abaissé en config
    d = _decide(policy=lax, n_evaluated=400)                        # 400 >= 300 -> PASS
    assert d.status == "SUPPORTED"
    sample = next(c for c in d.criteria if c.name == "min_sample_size")
    assert sample.threshold == 300 and sample.verdict is Verdict.PASS


# --- Verdict sur données RÉELLES : honnêtement EXPERIMENTAL -----------------------
def test_real_fl1_model_stays_experimental_mechanically():
    a = assess_default_one_x_two()
    assert a.decision.status == "EXPERIMENTAL"
    # Seuls les critères REQUIS et non-PASS bloquent la promotion.
    blockers = {c.name: c.verdict for c in a.decision.criteria
                if c.required and c.verdict is not Verdict.PASS}
    # Blocages ATTENDUS et honnêtes : échantillon d'une seule saison + CLV non collectée.
    assert blockers == {
        "min_sample_size": Verdict.FAIL,
        "positive_clv": Verdict.NOT_MEASURABLE,
    }
    # La fraîcheur live est désormais câblée -> mesurable -> PASS (plus un blocage).
    freshness = next(c for c in a.decision.criteria if c.name == "measurable_live_freshness")
    assert freshness.verdict is Verdict.PASS
    # max_fold_brier_spread est du MONITORING (non requis) : même s'il échouait, il
    # ne bloquerait pas — ici il n'est simplement pas dans les blockers requis.
    spread = next(c for c in a.decision.criteria if c.name == "max_fold_brier_spread")
    assert spread.required is False
    # Le modèle est néanmoins réel : il bat les baselines et est correctement calibré.
    passing = {c.name for c in a.decision.criteria if c.verdict is Verdict.PASS}
    assert {"must_beat_baselines", "max_calibration_error", "min_temporal_folds"} <= passing


def test_real_assessment_never_fabricates_clv():
    a = assess_default_one_x_two()
    assert a.observations.clv_status == CLV_NOT_YET_MEASURABLE
    assert a.observations.clv_mean is None          # jamais 0


def test_real_assessment_recommends_raw_probabilities():
    # Constat honnête : la re-calibration point-in-time n'améliore pas l'ECE sur FL1.
    a = assess_default_one_x_two()
    assert a.metrics["calibration"]["recommendation"]["use"] == "raw"
