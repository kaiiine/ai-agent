"""Découverte dynamique + isolation (§5/§11) : un batch MIXTE (compétitions
supportées et non supportées) n'arrête jamais le run — chaque événement reçoit un
statut typé, et la couverture est observable (découvert vs évaluable vs non-évaluable
par raison). Hermétique (stubs, zéro réseau).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.betting_engine.coverage import summarize_batch
from src.agents.quant.betting_engine.live_batch import evaluate_live_batch
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationResult,
    LiveEvaluationStatus,
)

_T = datetime(2025, 10, 4, 12, tzinfo=timezone.utc)


class _Event:
    def __init__(self, eid, competition, sport="football"):
        self.bookmaker_event_id = eid
        self.competition = competition
        self.sport = sport


def _catalogue(events):
    def scan(connector):
        return events
    return scan


def _evaluate_by_competition(supported_competition):
    """EVALUATED pour la compétition supportée, sinon COMPETITION_NOT_COVERED."""
    def evaluate(event, *, decision_time, event_resolver, sports_gateway):
        if event.competition == supported_competition:
            return LiveEvaluationResult(
                status=LiveEvaluationStatus.EVALUATED, reason="ok",
                decision_time=decision_time, bookmaker_event_id=event.bookmaker_event_id)
        return LiveEvaluationResult(
            status=LiveEvaluationStatus.COMPETITION_NOT_COVERED,
            reason=f"aucun modèle pour {event.competition}",
            decision_time=decision_time, bookmaker_event_id=event.bookmaker_event_id)
    return evaluate


def test_mixed_batch_isolates_unsupported_and_evaluates_supported():
    # A (MLS) non supportée, B (Ligue 1) supportée, C (Liga MX) non supportée.
    events = [_Event("a1", "MLS"), _Event("b1", "Ligue 1"), _Event("b2", "Ligue 1"),
              _Event("c1", "Liga MX")]
    batch = evaluate_live_batch(
        connector=None, sports_gateway=None, event_resolver=None,
        catalogue=_catalogue(events), evaluate=_evaluate_by_competition("Ligue 1"),
        now_fn=lambda: _T)

    # Le run n'est PAS arrêté par MLS/Liga MX : tous les événements ont un résultat.
    assert len(batch.results) == 4
    statuses = {e.bookmaker_event_id: r.status for e, r in batch.results}
    assert statuses["b1"] is LiveEvaluationStatus.EVALUATED
    assert statuses["b2"] is LiveEvaluationStatus.EVALUATED
    assert statuses["a1"] is LiveEvaluationStatus.COMPETITION_NOT_COVERED
    assert statuses["c1"] is LiveEvaluationStatus.COMPETITION_NOT_COVERED


def test_coverage_report_is_observable_and_honest():
    events = [_Event("a1", "MLS"), _Event("b1", "Ligue 1"), _Event("b2", "Ligue 1"),
              _Event("c1", "Liga MX")]
    batch = evaluate_live_batch(
        connector=None, sports_gateway=None, event_resolver=None,
        catalogue=_catalogue(events), evaluate=_evaluate_by_competition("Ligue 1"),
        now_fn=lambda: _T)

    report = summarize_batch(batch, "football")
    assert report.events_discovered == 4                     # catalogue coverage
    assert report.events_evaluable == 2                      # model coverage (Ligue 1)
    assert report.events_not_evaluable == 2                  # isolés, jamais perdus
    assert report.by_status["EVALUATED"] == 2
    assert report.by_status["COMPETITION_NOT_COVERED"] == 2
    # ventilation par compétition (raison de non-évaluabilité visible)
    by_comp = {c.competition: c for c in report.by_competition}
    assert by_comp["Ligue 1"].evaluable == 2
    assert by_comp["MLS"].evaluable == 0
    assert "COMPETITION_NOT_COVERED" in by_comp["MLS"].statuses


def test_empty_catalogue_is_zero_not_crash():
    batch = evaluate_live_batch(
        connector=None, sports_gateway=None, event_resolver=None,
        catalogue=_catalogue([]), evaluate=_evaluate_by_competition("Ligue 1"), now_fn=lambda: _T)
    report = summarize_batch(batch, "football")
    assert report.events_discovered == 0 and report.events_evaluable == 0
    assert report.evaluable_ratio == 0.0
