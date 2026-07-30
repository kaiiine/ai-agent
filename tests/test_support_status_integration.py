"""Statut de support DÉRIVÉ (jamais déclaratif) + intégration de la sélection BE.

Prouve : (1) sans décision persistée -> EXPERIMENTAL ; (2) une décision SUPPORTED
persistée -> SUPPORTED (résolveur non truqué) ; (3) une décision EXPERIMENTAL
persistée ne promeut jamais (aucun fallback silencieux) ; (4) manifest et modèle
lisent la même source ; (5) au point de sélection (value_engine), un modèle
EXPERIMENTAL ne produit JAMAIS de BET (ABSTAIN/MODEL_NOT_SUPPORTED) ; un modèle
SUPPORTED atteint réellement la branche supportée — laquelle est la FRONTIÈRE
money-sensitive explicitement différée (jamais un fallback silencieux).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness,
    MarketPrediction,
    PredictionExplanation,
    UncertaintyStatus,
)
from src.agents.quant.betting_engine.core.odds import OddsSnapshot
from src.agents.quant.betting_engine.maturity import (
    CriterionResult,
    ModelSupportDecision,
    Verdict,
)
from src.agents.quant.betting_engine.support_status import (
    append_support_decision,
    resolve_market_status,
)
from src.agents.quant.betting_engine.value_engine import EvaluationStatus, evaluate_selection

_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _market():
    return [
        OddsSnapshot("ev1", "MATCH_WINNER", "home", 2.15, _T, "winamax"),
        OddsSnapshot("ev1", "MATCH_WINNER", "draw", 3.40, _T, "winamax"),
        OddsSnapshot("ev1", "MATCH_WINNER", "away", 3.20, _T, "winamax"),
    ]


def _pred(status: DataReadiness) -> MarketPrediction:
    return MarketPrediction(
        "football", "MATCH_WINNER", "home", 0.55, 0.55, 0.55,
        UncertaintyStatus.NOT_ESTIMATED, "m.v0", 1.0, status, _T,
        PredictionExplanation([], set(), [], []),
    )


def _decision(status: str) -> ModelSupportDecision:
    return ModelSupportDecision(
        model_name="one_x_two", model_version="v0", status=status,
        policy_version="1", policy_checksum="abc",
        criteria=(CriterionResult("min_sample_size", True, 500, 800, Verdict.PASS, "ok"),),
        rationale="test", assessed_at=datetime.now(timezone.utc).isoformat(),
    )


# --- Résolveur : dérivé du ledger, jamais déclaratif ----------------------------
def test_absent_ledger_resolves_experimental(tmp_path):
    absent = tmp_path / "no_such_ledger.jsonl"
    assert resolve_market_status("one_x_two", "v0", ledger_path=absent) == DataReadiness.EXPERIMENTAL


def test_persisted_supported_decision_resolves_supported(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    append_support_decision(_decision("SUPPORTED"), ledger_path=ledger)
    assert resolve_market_status("one_x_two", "v0", ledger_path=ledger) == DataReadiness.SUPPORTED


def test_persisted_experimental_decision_never_promotes(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    append_support_decision(_decision("EXPERIMENTAL"), ledger_path=ledger)
    assert resolve_market_status("one_x_two", "v0", ledger_path=ledger) == DataReadiness.EXPERIMENTAL


def test_latest_decision_wins_no_silent_fallback(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    append_support_decision(_decision("SUPPORTED"), ledger_path=ledger)
    append_support_decision(_decision("EXPERIMENTAL"), ledger_path=ledger)   # révocation
    assert resolve_market_status("one_x_two", "v0", ledger_path=ledger) == DataReadiness.EXPERIMENTAL


def test_mismatched_version_does_not_resolve_supported(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    append_support_decision(_decision("SUPPORTED"), ledger_path=ledger)      # version v0
    assert resolve_market_status("one_x_two", "v999", ledger_path=ledger) == DataReadiness.EXPERIMENTAL


def test_ledger_refuses_home_axon():
    import pytest
    with pytest.raises(ValueError, match="axon"):
        append_support_decision(_decision("SUPPORTED"), ledger_path="~/.axon/l.jsonl")


# --- Manifest & modèle lisent la même source de vérité (dérivée) -----------------
def test_manifest_status_is_derived_and_experimental():
    from src.agents.quant.betting_engine.sports.football import manifest
    assert manifest.GLOBAL_MODEL_STATUS["MATCH_WINNER"] == DataReadiness.EXPERIMENTAL


def test_model_ceiling_is_experimental_by_default():
    from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel
    assert OneXTwoModel()._ceiling == DataReadiness.EXPERIMENTAL


# --- Sélection : EXPERIMENTAL -> jamais de BET ; SUPPORTED -> frontière money -----
def test_experimental_selection_never_bets_no_fallback():
    """BE-FR-011 au point de sélection : métriques calculées pour l'audit mais
    décision plafonnée ABSTAIN/MODEL_NOT_SUPPORTED. Aucun fallback silencieux."""
    d = evaluate_selection(_pred(DataReadiness.EXPERIMENTAL), _market())
    assert d.decision == "ABSTAIN"
    assert "MODEL_NOT_SUPPORTED" in d.reasons
    assert d.evaluation_status is EvaluationStatus.EVALUATED   # audit calculé, pas de BET


def test_supported_selection_reaches_deferred_money_frontier():
    """Un modèle SUPPORTED est réellement SÉLECTIONNÉ (la branche supportée est
    atteinte), et cette branche est la frontière money-sensitive explicitement
    différée (borne basse EV / model_reliability non implémentés) : elle échoue
    BRUYAMMENT (NotImplementedError), jamais par un fallback silencieux qui
    inventerait un BET ou masquerait un ABSTAIN."""
    with pytest.raises(NotImplementedError):
        evaluate_selection(_pred(DataReadiness.SUPPORTED), _market())
