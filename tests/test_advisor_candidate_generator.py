"""Candidate Generator (Lot 3) — dérivations autorisées + id stable + exposition.

Vérifie : id stable/déterministe, rejet cote/proba invalides, fair_odds exact,
EV basse sur probability_low, statut boosted préservé, plafonds non fabriqués
(None), clés d'exposition canoniques, aucune donnée sportive inventée.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.advisor.candidate_generation import (
    candidate_from_evaluation, generate_candidates,
)
from src.agents.quant.advisor.candidate_generation.normalization import fair_odds_from_probability
from src.agents.quant.advisor.domain.candidates import CandidateBet
from src.agents.quant.advisor.input_adapter.schema import (
    AdaptedBatch, AdaptedEvaluation, AdaptedExplanation,
)

_KO = datetime(2025, 10, 5, 17, tzinfo=timezone.utc)
_DEC = datetime(2025, 10, 4, 12, tzinfo=timezone.utc)
_OBS = datetime(2025, 10, 4, 11, 30, tzinfo=timezone.utc)   # instant d'observation des cotes
_EVENT = "event:football:fra:ligue1:psg-marseille:2025-10-05"


def _adapted(**kw) -> AdaptedEvaluation:
    base = dict(
        schema_version="1", event_id=_EVENT, sport="football",
        competition_id="competition:football:fra:ligue1", scheduled_at=_KO,
        participant_ids=("team:football:fra:psg", "team:football:fra:marseille"),
        observed_at=_OBS,
        bookmaker="winamax", market_id="winamax:%s:MATCH_WINNER" % _EVENT,
        market_type="MATCH_WINNER", selection="home",
        bookmaker_odds=Decimal("2.00"), fair_probability=Decimal("0.55"),
        probability_low=Decimal("0.55"), probability_high=Decimal("0.55"),
        uncertainty_status="NOT_ESTIMATED", model_version="dixon_coles.v1",
        model_maturity="EXPERIMENTAL", data_quality=Decimal("1.0"),
        calibration_score=None, freshness_score=None, liquidity_score=None,
        implied_probability_raw=Decimal("0.5000"), no_vig_probability=Decimal("0.52"),
        edge=Decimal("0.03"), expected_value=Decimal("0.10"),
        is_boosted=False, decision="ABSTAIN", decision_reasons=("MODEL_NOT_SUPPORTED",),
        warnings=("freshness_unavailable: gateway",),
        explanation=AdaptedExplanation(
            top_features=(("form_diff", 1.2),), missing_features=frozenset(),
            confidence_drivers=("home_form",), warnings=("freshness_unavailable: gateway",)),
        source_decision_id=None,
    )
    base.update(kw)
    return AdaptedEvaluation(**base)


def _batch(*evs, decision_time=_DEC) -> AdaptedBatch:
    return AdaptedBatch(schema_version="1", decision_time=decision_time,
                        evaluations=tuple(evs), skipped=())


def _candidate(**kw) -> CandidateBet:
    return candidate_from_evaluation(_adapted(**kw))


# ── Id = identité de l'OFFRE observée (ADR-ADV-003), pas de la requête ─────────
def test_same_input_same_id():
    assert _candidate().candidate_id == _candidate().candidate_id


def test_same_snapshot_same_id_across_requests():
    """Même offre / même snapshot (observed_at) / requêtes Advisor différentes
    (decision_time distincts) -> MÊME candidate_id : l'id identifie l'offre, pas
    la requête."""
    ev = _adapted()                                 # même observed_at (_OBS)
    req_a = AdaptedBatch("1", datetime(2025, 10, 4, 12, tzinfo=timezone.utc), (ev,), ())
    req_b = AdaptedBatch("1", datetime(2025, 10, 4, 18, tzinfo=timezone.utc), (ev,), ())
    assert generate_candidates(req_a)[0].candidate_id == generate_candidates(req_b)[0].candidate_id


def test_different_observed_at_changes_id():
    a = candidate_from_evaluation(_adapted(observed_at=_OBS))
    b = candidate_from_evaluation(_adapted(observed_at=datetime(2025, 10, 4, 15, tzinfo=timezone.utc)))
    assert a.candidate_id != b.candidate_id          # snapshot différent -> id différent


def test_id_depends_on_selection():
    home = _candidate(selection="home")
    away = _candidate(selection="away")
    assert home.candidate_id != away.candidate_id


# ── Cote / probabilité invalides ──────────────────────────────────────────────
def test_zero_probability_rejected():
    with pytest.raises(ValueError):
        _candidate(fair_probability=Decimal("0"), probability_low=Decimal("0"),
                   probability_high=Decimal("0"))


def test_invalid_odds_rejected():
    with pytest.raises(ValueError):
        _candidate(bookmaker_odds=Decimal("1.00"))          # <= 1 (CandidateBet)


def test_missing_value_metrics_rejected():
    with pytest.raises(ValueError):
        _candidate(implied_probability_raw=None)             # boosté/non évalué : jamais fabriqué


# ── fair_odds exact ───────────────────────────────────────────────────────────
def test_fair_odds_exact():
    assert fair_odds_from_probability(Decimal("0.5")) == Decimal("2")
    assert fair_odds_from_probability(Decimal("0.25")) == Decimal("4")
    c = _candidate(fair_probability=Decimal("0.50"), probability_low=Decimal("0.50"),
                   probability_high=Decimal("0.50"))
    assert c.fair_odds == Decimal("2")


# ── EV basse : utilise probability_low ────────────────────────────────────────
def test_expected_value_low_uses_probability_low():
    c = _candidate(fair_probability=Decimal("0.55"), probability_low=Decimal("0.45"),
                   probability_high=Decimal("0.60"), bookmaker_odds=Decimal("2.00"))
    assert c.expected_value_mean == Decimal("0.10")          # 0.55*2 - 1
    assert c.expected_value_low == Decimal("-0.10")          # 0.45*2 - 1 (borne basse)
    assert c.expected_value_low < c.expected_value_mean


def test_edge_follows_betting_engine_no_vig():
    # Définition canonique du moteur : edge = fair_probability − no_vig_probability.
    c = _candidate(fair_probability=Decimal("0.55"), probability_low=Decimal("0.45"),
                   probability_high=Decimal("0.60"),
                   implied_probability_raw=Decimal("0.50"), no_vig_probability=Decimal("0.52"))
    assert c.edge_mean == Decimal("0.03")                    # 0.55 - 0.52 (no_vig)
    assert c.edge_low == Decimal("-0.07")                    # 0.45 - 0.52
    assert c.implied_probability == Decimal("0.50")          # implicite BRUTE, propagée (≠ seuil edge)


# ── Statut boosted préservé ───────────────────────────────────────────────────
def test_boost_status_preserved():
    assert _candidate(is_boosted=False).is_boosted is False
    assert _candidate(is_boosted=True).is_boosted is True    # le flag traverse tel quel


# ── Plafonds non fabriqués ────────────────────────────────────────────────────
def test_caps_are_none_never_fabricated():
    c = _candidate()
    assert c.max_stake is None and c.max_payout is None      # non exposés (Vague 2), jamais inventés


def test_missing_scores_stay_none():
    c = _candidate()
    assert c.calibration_score is None and c.freshness_score is None and c.liquidity_score is None


# ── Clés d'exposition canoniques (ADR-ADV-008) ────────────────────────────────
def test_exposure_keys_are_canonical():
    keys = _candidate().exposure_keys
    assert f"event:{_EVENT}" in keys
    assert "competition:competition:football:fra:ligue1" in keys
    assert "market:MATCH_WINNER" in keys
    assert "bookmaker:winamax" in keys
    assert "participant:team:football:fra:psg" in keys
    assert "participant:team:football:fra:marseille" in keys


# ── Métadonnées propagées, jamais rehaussées ──────────────────────────────────
def test_maturity_and_warnings_propagated():
    c = _candidate()
    assert c.model_maturity == "EXPERIMENTAL"                # jamais SUPPORTED
    assert any(w.startswith("freshness_unavailable") for w in c.warnings)
    assert c.source_decision_id is None                      # Q5 : jamais inventé
    assert c.explanation_ref == f"expl:{c.candidate_id}"


# ── Génération sur un batch : déterministe, indépendante de l'ordre pour l'id ──
def test_generate_candidates_over_batch():
    evs = (_adapted(selection="home"), _adapted(selection="draw"), _adapted(selection="away"))
    cands = generate_candidates(_batch(*evs))
    assert [c.selection for c in cands] == ["home", "draw", "away"]   # ordre d'entrée préservé
    # l'IDENTITÉ ne dépend pas de l'ordre d'entrée
    shuffled = generate_candidates(_batch(evs[2], evs[0], evs[1]))
    assert {c.candidate_id for c in cands} == {c.candidate_id for c in shuffled}


def test_generated_candidate_is_valid_decimal_contract():
    c = _candidate()
    for name in ("fair_odds", "edge_mean", "edge_low",
                 "expected_value_mean", "expected_value_low", "implied_probability"):
        value = getattr(c, name)
        assert isinstance(value, Decimal) and not isinstance(value, float), name
