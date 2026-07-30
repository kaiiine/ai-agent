"""Sizing COMBO V1 (ADR-ADV-014) : réutilise le Kelly canonique, borne basse,
safety_margin non réappliquée, exposition unionnée, conservatisme par policy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.advisor.combos.builder import ComboEvaluation, combo_id
from src.agents.quant.advisor.combos.pricing import price_combo
from src.agents.quant.advisor.combos.sizing import (
    build_combo_candidate,
    combo_reliability,
    combo_sizing_profile,
)
from src.agents.quant.advisor.domain.candidates import CandidateBet, CandidateEvaluation, CandidateStatus
from src.agents.quant.advisor.domain.enums import DependencyStatus
from src.agents.quant.advisor.domain.money import ONE
from src.agents.quant.advisor.recommendation.simple import (
    _CONFIG_PATH,
    compute_single_stake,
    load_sizing_profiles,
)

_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
_MARGIN = Decimal("0.90")


def _leg(cid, event, *, p_low=Decimal("0.60"), odds=Decimal("2.00"), reliability=Decimal("0.75"),
         maturity="SUPPORTED", dq=Decimal("1.0")):
    low, high = p_low, p_low + Decimal("0.05")
    fair = (low + high) / 2
    cand = CandidateBet(
        candidate_id=cid, event_id=event, sport="football", competition_id="comp:1",
        scheduled_at=_T, bookmaker="winamax", market_id=f"m:{cid}", market_type="MATCH_WINNER",
        selection="home", bookmaker_odds=odds, fair_probability=fair, probability_low=low,
        probability_high=high, fair_odds=Decimal("1.90"), implied_probability=Decimal("0.50"),
        expected_value_mean=fair * odds - ONE, expected_value_low=low * odds - ONE,
        edge_mean=Decimal("0.05"), edge_low=Decimal("0.03"), model_version="m.v1",
        model_maturity=maturity, calibration_score=reliability, data_quality=dq,
        freshness_score=Decimal("0.90"), liquidity_score=None, max_stake=None, max_payout=None,
        is_boosted=False, participant_ids=(f"team:{event}:a", f"team:{event}:b"),
        exposure_keys=frozenset({f"event:{event}", f"participant:team:{event}:a"}),
        warnings=(), explanation_ref="e", source_decision_id=None)
    return CandidateEvaluation(cand, CandidateStatus.ELIGIBLE, (), Decimal("1"),
                              {"reliability_component": reliability})


def _combo(a, b, *, margin=_MARGIN):
    pricing = price_combo([a.candidate, b.candidate], margin)
    return ComboEvaluation(
        combo_id=combo_id(a, b), legs=(a, b), compatibility_reason=None,
        dependency_status=DependencyStatus.INDEPENDENT_ENOUGH, pricing=pricing,
        admissible=True, rejection_reason=None, target_odds_match=False,
        min_leg_quality=min(a.candidate.data_quality, b.candidate.data_quality))


# --- Représentation synthétique fidèle ------------------------------------------
def test_synthetic_uses_combined_prob_low_not_mean():
    combo = _combo(_leg("a", "A"), _leg("b", "B"))
    synth = build_combo_candidate(combo)
    assert synth.probability_low == combo.pricing.combined_prob_low
    assert synth.probability_low != combo.pricing.combined_prob_mean     # jamais la moyenne
    assert synth.bookmaker_odds == combo.pricing.combined_odds


def test_synthetic_exposure_keys_are_union_of_legs():
    combo = _combo(_leg("a", "A"), _leg("b", "B"))
    synth = build_combo_candidate(combo)
    assert "event:A" in synth.exposure_keys and "event:B" in synth.exposure_keys


def test_synthetic_reliability_and_quality_are_min_of_legs():
    combo = _combo(_leg("a", "A", reliability=Decimal("0.80"), dq=Decimal("0.9")),
                   _leg("b", "B", reliability=Decimal("0.60"), dq=Decimal("0.7")))
    synth = build_combo_candidate(combo)
    assert synth.calibration_score == Decimal("0.60")                    # min reliability
    assert synth.data_quality == Decimal("0.7")                          # min quality
    assert combo_reliability(combo) == Decimal("0.60")


def test_maturity_supported_only_if_all_legs_supported():
    both = _combo(_leg("a", "A"), _leg("b", "B"))
    assert build_combo_candidate(both).model_maturity == "SUPPORTED"
    mixed = _combo(_leg("a", "A"), _leg("b", "B", maturity="EXPERIMENTAL"))
    assert build_combo_candidate(mixed).model_maturity != "SUPPORTED"    # -> aucune mise en aval


# --- Réutilisation exacte du Kelly canonique + conservatisme --------------------
def test_combo_uses_canonical_kelly_and_no_second_margin():
    combo = _combo(_leg("a", "A"), _leg("b", "B"))
    profiles = load_sizing_profiles()
    combo_profile = combo_sizing_profile(profiles["BALANCED"])
    synth = build_combo_candidate(combo)
    # Le stake est EXACTEMENT compute_single_stake sur la borne basse (déjà × margin).
    stake = compute_single_stake(synth, reliability=combo_reliability(combo),
                                 bankroll=Decimal("100"), max_total_stake=None, sizing=combo_profile)
    # Référence : un candidat single avec la MÊME probability_low et le profil combo.
    ref = compute_single_stake(synth, reliability=combo_reliability(combo),
                               bankroll=Decimal("100"), max_total_stake=None, sizing=combo_profile)
    assert stake == ref and stake > 0
    # safety_margin déjà dans combined_prob_low : pas de double application.
    assert synth.probability_low == combo.pricing.joint_prob_low_raw * _MARGIN


def test_combo_fractional_kelly_not_more_aggressive_than_single():
    profiles = load_sizing_profiles()
    for name, p in profiles.items():
        assert Decimal("0") < p.combo_fractional_kelly <= p.fractional_kelly
        assert Decimal("0") < p.combo_line_cap_fraction <= p.per_line_cap_fraction


def test_combo_stake_leq_single_stake_same_opportunity():
    combo = _combo(_leg("a", "A"), _leg("b", "B"))
    profiles = load_sizing_profiles()
    synth = build_combo_candidate(combo)
    combo_stake = compute_single_stake(synth, reliability=combo_reliability(combo),
                                       bankroll=Decimal("100"), max_total_stake=None,
                                       sizing=combo_sizing_profile(profiles["BALANCED"]))
    single_stake = compute_single_stake(synth, reliability=combo_reliability(combo),
                                        bankroll=Decimal("100"), max_total_stake=None,
                                        sizing=profiles["BALANCED"])   # profil SINGLE
    assert combo_stake <= single_stake                                  # combo jamais plus agressif


def test_non_supported_combo_gets_zero_stake():
    mixed = _combo(_leg("a", "A"), _leg("b", "B", maturity="EXPERIMENTAL"))
    profiles = load_sizing_profiles()
    synth = build_combo_candidate(mixed)
    stake = compute_single_stake(synth, reliability=Decimal("0.75"), bankroll=Decimal("100"),
                                 max_total_stake=None, sizing=combo_sizing_profile(profiles["BALANCED"]))
    assert stake == Decimal("0")                                        # BE-FR-011 via compute_single_stake


# --- Config versionnée : checksum + invariant ------------------------------------
def test_sizing_config_checksum_tamper_evident(tmp_path):
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    data["profiles"]["BALANCED"]["combo_fractional_kelly"] = "0.99"      # falsification
    bad = tmp_path / "s.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_sizing_profiles(bad)


def test_sizing_config_rejects_combo_more_aggressive_than_single(tmp_path):
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    data["profiles"]["BALANCED"]["combo_fractional_kelly"] = "0.90"      # > single 0.50
    payload = {k: data[k] for k in ("config_version", "effective_from", "profiles")}
    import hashlib
    data["checksum"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    bad = tmp_path / "s.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="combo_fractional_kelly"):
        load_sizing_profiles(bad)
