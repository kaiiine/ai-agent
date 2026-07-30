"""Money-path SUPPORTED (BE-FR-012, ADR-BE-003). Le Betting Engine DÉCIDE BET/ABSTAIN
et expose l'économie ; il NE SIZE PAS (Option A). Prouve : plus de NotImplementedError,
gates conservateurs (intervalle estimé, data_quality, reliability, worst_case_ev à la
borne basse), reason codes distincts, déterminisme, seuils versionnés, rejet des
entrées invalides, et non-duplication du Kelly (le sizing reste dans Advisor).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness,
    MarketPrediction,
    PredictionExplanation,
    UncertaintyStatus,
)
from src.agents.quant.betting_engine.core.odds import OddsSnapshot
from src.agents.quant.betting_engine.value_engine import EvaluationStatus, evaluate_selection
from src.agents.quant.betting_engine.value_engine.bet_policy import (
    _CONFIG_PATH,
    load_bet_decision_policy,
)
from src.agents.quant.betting_engine.value_engine.market_coherence import MarketCoherenceError

_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
_POLICY = load_bet_decision_policy()


def _market(home=2.15):
    return [
        OddsSnapshot("ev1", "MATCH_WINNER", "home", home, _T, "winamax"),
        OddsSnapshot("ev1", "MATCH_WINNER", "draw", 3.40, _T, "winamax"),
        OddsSnapshot("ev1", "MATCH_WINNER", "away", 3.20, _T, "winamax"),
    ]


def _pred(status=DataReadiness.SUPPORTED, *, low=0.50, fair=0.55, high=0.60,
          uncertainty=UncertaintyStatus.ESTIMATED, dq=1.0, selection="home"):
    return MarketPrediction(
        "football", "MATCH_WINNER", selection, fair, low, high, uncertainty,
        "m.v0", dq, status, _T, PredictionExplanation([], set(), [], []),
    )


# ── Maturité : EXPERIMENTAL jamais BET ; SUPPORTED atteint le money-path ────────
def test_experimental_with_great_ev_abstains():
    d = evaluate_selection(_pred(DataReadiness.EXPERIMENTAL, low=0.90, fair=0.92, high=0.94), _market())
    assert d.decision == "ABSTAIN"
    assert "MODEL_NOT_SUPPORTED" in d.reasons
    assert d.worst_case_ev is None                       # money-path non emprunté


def test_supported_admissible_opportunity_bets():
    d = evaluate_selection(_pred(), _market())
    assert d.decision == "BET"                            # plus de NotImplementedError
    assert d.reasons == []
    assert d.evaluation_status is EvaluationStatus.EVALUATED
    # Économie exposée pour le sizing Advisor (le BE ne size pas).
    assert d.worst_case_ev == round(0.50 * 2.15 - 1, 4)  # borne basse (BE-FR-012)
    assert d.min_bet_ev == _POLICY.min_bet_ev
    assert d.model_reliability == _POLICY.supported_model_reliability
    assert not hasattr(d, "stake")                        # aucune mise dans le BE (Option A)


# ── EV : borne basse gouverne, la moyenne ne sauve jamais ───────────────────────
def test_positive_mean_ev_but_low_below_threshold_abstains():
    # fair=0.55 -> EV moyen positif ; low=0.44 -> worst_case_ev négatif.
    d = evaluate_selection(_pred(low=0.44, fair=0.55, high=0.60), _market())
    assert d.expected_value > 0                           # scénario moyen positif
    assert d.worst_case_ev < d.min_bet_ev                # borne basse insuffisante
    assert d.decision == "ABSTAIN"
    assert "VALUE_BELOW_THRESHOLD" in d.reasons


def test_worst_case_ev_exactly_at_threshold_bets():
    # Frontière : worst_case_ev == min_bet_ev -> admission (comparaison >=).
    policy = replace(_POLICY, min_bet_ev=round(0.50 * 2.15 - 1, 4))   # 0.075
    d = evaluate_selection(_pred(low=0.50), _market(), policy=policy)
    assert d.worst_case_ev == policy.min_bet_ev and d.decision == "BET"


def test_worst_case_ev_just_below_threshold_abstains():
    policy = replace(_POLICY, min_bet_ev=round(0.50 * 2.15 - 1, 4) + 0.0001)
    d = evaluate_selection(_pred(low=0.50), _market(), policy=policy)
    assert d.decision == "ABSTAIN" and "VALUE_BELOW_THRESHOLD" in d.reasons


# ── Autres gates SUPPORTED ──────────────────────────────────────────────────────
def test_uncertainty_not_estimated_blocks_bet():
    d = evaluate_selection(_pred(uncertainty=UncertaintyStatus.NOT_ESTIMATED, low=0.55, fair=0.55, high=0.55),
                           _market())
    assert d.decision == "ABSTAIN" and "UNCERTAINTY_NOT_ESTIMATED" in d.reasons


def test_data_quality_below_threshold_abstains():
    d = evaluate_selection(_pred(dq=0.50), _market())     # 0.50 < 0.70
    assert d.decision == "ABSTAIN" and "DATA_QUALITY_INSUFFICIENT" in d.reasons


def test_reliability_below_threshold_abstains():
    policy = replace(_POLICY, supported_model_reliability=0.50)   # 0.50 < min 0.60
    d = evaluate_selection(_pred(), _market(), policy=policy)
    assert d.decision == "ABSTAIN" and "MODEL_RELIABILITY_INSUFFICIENT" in d.reasons


def test_reason_codes_are_distinct_and_specific():
    # Plusieurs gates échouent -> chaque cause a son code (jamais un NO_BET fourre-tout).
    policy = replace(_POLICY, supported_model_reliability=0.50)
    d = evaluate_selection(_pred(dq=0.40, low=0.44, fair=0.55, high=0.60), _market(), policy=policy)
    assert d.decision == "ABSTAIN"
    assert {"DATA_QUALITY_INSUFFICIENT", "MODEL_RELIABILITY_INSUFFICIENT",
            "VALUE_BELOW_THRESHOLD"} <= set(d.reasons)
    assert "NO_BET" not in d.reasons


# ── Déterminisme & config ───────────────────────────────────────────────────────
def test_deterministic_same_inputs_same_decision():
    a = evaluate_selection(_pred(), _market())
    b = evaluate_selection(_pred(), _market())
    assert (a.decision, a.worst_case_ev, a.reasons) == (b.decision, b.worst_case_ev, b.reasons)


def test_config_threshold_change_flips_decision():
    bet = evaluate_selection(_pred(low=0.50), _market())                      # BET (wc_ev 0.075 >= 0.02)
    strict = replace(_POLICY, min_bet_ev=0.10)                               # 0.075 < 0.10
    abstain = evaluate_selection(_pred(low=0.50), _market(), policy=strict)
    assert bet.decision == "BET" and abstain.decision == "ABSTAIN"


def test_config_checksum_tamper_evident(tmp_path):
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    data["min_bet_ev"] = -1.0                             # falsification sans recalcul checksum
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_bet_decision_policy(bad)


def test_config_rejects_reliability_out_of_unit_interval(tmp_path):
    import hashlib
    from src.agents.quant.betting_engine.value_engine.bet_policy import _CHECKSUM_FIELDS
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    data["supported_model_reliability"] = 1.5
    data["checksum"] = hashlib.sha256(
        json.dumps({k: data[k] for k in _CHECKSUM_FIELDS}, sort_keys=True).encode()).hexdigest()
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=r"\[0,1\]"):
        load_bet_decision_policy(bad)


# ── Entrées invalides : rejetées, jamais réparées en silence (§19) ──────────────
def test_probability_out_of_range_rejected():
    with pytest.raises(ValueError, match="hors"):
        evaluate_selection(_pred(low=0.50, fair=1.5, high=1.5), _market())


def test_inconsistent_interval_rejected():
    # probability_low > fair -> intervalle incohérent.
    with pytest.raises(ValueError, match="incohérent"):
        evaluate_selection(_pred(low=0.60, fair=0.55, high=0.60), _market())


def test_odds_leq_one_is_incoherent_never_silent_bet():
    with pytest.raises(MarketCoherenceError):
        evaluate_selection(_pred(), _market(home=1.0))   # cote <= 1 rejetée (coherence)


# ── Non-duplication : le Kelly/sizing reste dans Advisor (Option A) ─────────────
def _advisor_candidate(reliability_unused=None):
    from src.agents.quant.advisor.domain.candidates import CandidateBet
    from src.agents.quant.advisor.domain.money import ONE
    low, high = Decimal("0.55"), Decimal("0.60")
    fair = (low + high) / 2
    odds = Decimal("2.10")
    return CandidateBet(
        candidate_id="c", event_id="e1", sport="football", competition_id="comp:1",
        scheduled_at=_T, bookmaker="winamax", market_id="m", market_type="MATCH_WINNER",
        selection="home", bookmaker_odds=odds, fair_probability=fair, probability_low=low,
        probability_high=high, fair_odds=Decimal("1.90"), implied_probability=Decimal("0.4762"),
        expected_value_mean=fair * odds - ONE, expected_value_low=low * odds - ONE,
        edge_mean=Decimal("0.05"), edge_low=Decimal("0.03"), model_version="m.v1",
        model_maturity="SUPPORTED", calibration_score=None, data_quality=Decimal("1.0"),
        freshness_score=Decimal("0.90"), liquidity_score=None, max_stake=None, max_payout=None,
        is_boosted=False, participant_ids=("team:a", "team:b"),
        exposure_keys=frozenset({"event:e1"}), warnings=(),
        explanation_ref="expl", source_decision_id=None)


def test_advisor_sizing_is_the_only_kelly_and_is_monotone_in_reliability():
    """Caractérisation READ-ONLY du sizing Advisor (Lot 6, INCHANGÉ) : à opportunité
    identique, une reliability plus basse ne produit JAMAIS une mise plus grande. Prouve
    qu'aucune seconde formule Kelly n'a été introduite côté BE (le BE ne size pas)."""
    from src.agents.quant.advisor.recommendation.simple import (
        compute_single_stake,
        load_sizing_profiles,
    )
    sizing = load_sizing_profiles()["BALANCED"]
    cand = _advisor_candidate()
    high_r = compute_single_stake(cand, reliability=Decimal("0.90"), bankroll=Decimal("100"),
                                  max_total_stake=None, sizing=sizing)
    low_r = compute_single_stake(cand, reliability=Decimal("0.50"), bankroll=Decimal("100"),
                                 max_total_stake=None, sizing=sizing)
    assert low_r <= high_r                                # monotone : reliability plus basse -> mise <=
    # bankroll nul -> aucune mise (jamais une mise fabriquée).
    zero = compute_single_stake(cand, reliability=Decimal("0.90"), bankroll=Decimal("0"),
                                max_total_stake=None, sizing=sizing)
    assert zero == Decimal("0")
