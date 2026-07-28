"""Frontière de domaine `evaluate_live_batch` (Q4).

Deux garanties :
  1. le module batch n'a AUCUNE dépendance d'interface (argparse/cli/rendu) ;
     un futur adaptateur Advisor peut donc en dépendre sans importer `cli.py` ;
  2. le contrat est utilisable STANDALONE — avec des stubs triviaux, sans CLI et
     sans machinerie sport — en conservant ses invariants (decision_time capturé
     une fois APRÈS le scan, appariement événement↔résultat, isolation des
     échecs individuels, instantané immuable).
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.live_batch import (
    LiveEvaluationBatch,
    evaluate_live_batch,
)
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationResult,
    LiveEvaluationStatus as St,
)

_MODULE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "agents" / "quant" / "betting_engine" / "live_batch.py"
)
_T = datetime(2025, 10, 4, 12, tzinfo=timezone.utc)


# ── Invariant Q4 : le domaine n'importe aucune couche d'interface ─────────────
def _import_targets(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module
            for alias in node.names:                 # capture `from . import cli`
                yield alias.name


def test_live_batch_has_no_interface_dependency():
    """Scénario de violation : quelqu'un réintroduit `import argparse` ou
    `from .cli import run_live` dans le module batch pour réutiliser du rendu ou
    du parsing — recréant exactement le couplage que cette unité supprime."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    forbidden = [
        t for t in _import_targets(tree)
        if t == "argparse" or t.split(".")[-1] == "cli"
    ]
    assert not forbidden, (
        "la frontière de domaine batch ne doit dépendre d'aucune couche "
        f"d'interface (argparse/cli) : {forbidden}"
    )


# ── Stubs triviaux (aucune machinerie sport / réseau) ─────────────────────────
class _Event:
    def __init__(self, eid: str):
        self.bookmaker_event_id = eid


class _Connector:
    def __init__(self, events, *, raise_exc=None):
        self._events, self._raise = events, raise_exc


def _catalogue(events, *, raise_exc=None, log=None):
    def scan(connector):
        if log is not None:
            log.append("scan")
        if raise_exc is not None:
            raise raise_exc
        return list(events)
    return scan


def _refusal_evaluate(event, *, decision_time, event_resolver, sports_gateway):
    # Statut de refus volontaire : le batch est agnostique du statut ; on ne
    # fabrique donc AUCUN EVALUATED factice.
    return LiveEvaluationResult(
        status=St.SPORT_NOT_SUPPORTED, reason="stub",
        decision_time=decision_time, bookmaker_event_id=event.bookmaker_event_id,
    )


# ── Smoke standalone : utilisable sans CLI, invariants préservés ──────────────
def test_evaluate_live_batch_usable_standalone():
    calls = []
    log = []

    def spy_evaluate(event, *, decision_time, **kw):
        calls.append(decision_time)
        return _refusal_evaluate(event, decision_time=decision_time, **kw)

    def now_fn():
        log.append("now")
        return _T

    events = [_Event("A"), _Event("B")]
    batch = evaluate_live_batch(
        _Connector(events), sports_gateway=object(), event_resolver=object(),
        catalogue=_catalogue(events, log=log), evaluate=spy_evaluate, now_fn=now_fn,
    )

    assert isinstance(batch, LiveEvaluationBatch)
    assert log == ["scan", "now"]                    # decision_time capturé APRÈS le scan
    assert batch.decision_time == _T
    assert calls == [_T, _T]                          # même instant pour chaque événement
    assert isinstance(batch.results, tuple)           # instantané immuable
    assert [e.bookmaker_event_id for e, _ in batch.results] == ["A", "B"]  # appariement ordonné


def test_scan_failure_propagates_to_caller():
    boom = RuntimeError("PRELOADED_STATE introuvable")
    with pytest.raises(RuntimeError):
        evaluate_live_batch(
            _Connector([], raise_exc=boom), sports_gateway=object(), event_resolver=object(),
            catalogue=_catalogue([], raise_exc=boom), evaluate=_refusal_evaluate, now_fn=lambda: _T,
        )


def test_individual_event_failure_is_isolated():
    def flaky(event, *, decision_time, **kw):
        if event.bookmaker_event_id == "BAD":
            raise ValueError("boom interne")
        return _refusal_evaluate(event, decision_time=decision_time, **kw)

    events = [_Event("BAD"), _Event("OK")]
    batch = evaluate_live_batch(
        _Connector(events), sports_gateway=object(), event_resolver=object(),
        catalogue=_catalogue(events), evaluate=flaky, now_fn=lambda: _T,
    )
    by_id = {e.bookmaker_event_id: r for e, r in batch.results}
    assert len(batch.results) == 2                    # le batch continue
    assert by_id["BAD"].status is St.GATEWAY_UNAVAILABLE
    assert by_id["BAD"].error_context["type"] == "ValueError"
    assert by_id["OK"].status is St.SPORT_NOT_SUPPORTED


def test_batch_is_frozen_snapshot():
    batch = evaluate_live_batch(
        _Connector([]), sports_gateway=object(), event_resolver=object(),
        catalogue=_catalogue([]), evaluate=_refusal_evaluate, now_fn=lambda: _T,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        batch.decision_time = _T                      # type: ignore[misc]
