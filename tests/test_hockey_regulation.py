"""Hockey NHL — résultat RÉGLEMENTAIRE 3-way (Elo+Davidson), données réelles (§3/§11/§29).

Prouve : marché 3-way réglementaire honnêtement reconstruit (nul ~22 %), méthodologie
Davidson (PAS Dixon-Coles), skill validé hors échantillon, sans fuite, EXPERIMENTAL.
"""

from __future__ import annotations

import inspect
from dataclasses import replace

from src.agents.quant.betting_engine.sports import threeway_davidson as TD
from src.agents.quant.betting_engine.sports.hockey.regulation import (
    NHL_PARAMS, assess_nhl, load_nhl_regulation,
)
from src.agents.quant.betting_engine.sports.threeway_davidson import davidson_probs, run_threeway_elo


def test_regulation_dataset_has_three_outcomes():
    games, fingerprint = load_nhl_regulation()
    assert len(games) > 2000 and fingerprint.startswith("sha256:")
    from collections import Counter
    dist = Counter(g.outcome for g in games)
    assert set(dist) == {"home", "draw", "away"}
    assert 0.15 < dist["draw"] / len(games) < 0.30           # ~22 % de nuls réglementaires (NHL)


def test_methodology_is_davidson_not_dixon_coles():
    src = inspect.getsource(TD)
    assert "dixon_coles" not in src and "Davidson" in src    # §3 : jamais Dixon-Coles pour un autre sport
    p = davidson_probs(1600.0, 1500.0, 28.0, 0.6)
    assert abs(p["home"] + p["draw"] + p["away"] - 1.0) < 1e-9   # distribution valide (somme 1)
    assert p["home"] > p["away"] and p["draw"] > 0               # nul a une masse (ν>0)


def test_experimental_beats_baseline_on_brier_and_logloss():
    a = assess_nhl()
    o, d, m = a.observations, a.decision, a.metrics
    assert d.status == "EXPERIMENTAL"                        # mécanique, jamais SUPPORTED
    assert m["beats_baseline"] is True and o.model_brier < o.best_baseline_brier
    assert o.n_evaluated > 500 and o.calibration_error < 0.05
    # Freshness désormais CÂBLÉE (test_hockey_live) -> le SEUL blocker restant est la CLV
    # réelle (positive_clv), infabricable. Hockey est à une donnée de SUPPORTED (§2).
    blockers = {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}
    assert blockers == {"positive_clv"}


def test_no_future_leakage_threeway():
    games, _ = load_nhl_regulation()
    ordered = sorted(games, key=lambda g: g.tipoff)
    mid = ordered[len(ordered) // 2]
    run1 = run_threeway_elo(games, NHL_PARAMS)
    modified = [replace(g, outcome="draw" if g.outcome != "draw" else "home") if g.game_id == mid.game_id else g
                for g in games]
    run2 = run_threeway_elo(modified, NHL_PARAMS)
    t = {g.game_id: g.tipoff for g in games}
    idx2 = {gid: i for i, gid in enumerate(run2.predicted_game_ids)}
    checked = 0
    for gid, (prob, _) in zip(run1.predicted_game_ids, run1.model_predictions):
        if t[gid] < mid.tipoff:
            assert run2.model_predictions[idx2[gid]][0] == prob
            checked += 1
    assert checked > 100


def test_deterministic():
    assert assess_nhl().observations.model_brier == assess_nhl().observations.model_brier
