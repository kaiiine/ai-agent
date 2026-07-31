"""NFL moneyline (Elo pairwise) — données RÉELLES api-sports, hermétique (§3/§4/§13).

Sémantique VÉRIFIÉE sur payload Winamax (2-way « Vainqueur », pas de nul). Skill VALIDÉ
hors échantillon. Params propres NFL. Verdict mécanique EXPERIMENTAL, sans fuite.
"""

from __future__ import annotations

from dataclasses import replace

from src.agents.quant.betting_engine.sports.american_football.moneyline import (
    NFL_PARAMS, assess_nfl, load_nfl_games,
)
from src.agents.quant.betting_engine.sports.baseball.moneyline import MLB_PARAMS
from src.agents.quant.betting_engine.sports.pairwise_elo import run_pairwise_elo


def test_dataset_real_and_no_ties():
    games, fingerprint = load_nfl_games()
    assert len(games) > 500 and fingerprint.startswith("sha256:")
    assert all(g.home_score != g.away_score for g in games)


def test_params_specific_to_nfl():
    # §7 : params justifiés, non copiés (K=20 mais home_edge=48, distinct baseball/basket).
    assert NFL_PARAMS.home_edge == 48.0 and NFL_PARAMS.home_edge != MLB_PARAMS.home_edge
    assert NFL_PARAMS.min_prior_games == 6 and NFL_PARAMS.notes


def test_experimental_beats_baseline_and_passes_sample():
    a = assess_nfl()
    o, d, m = a.observations, a.decision, a.metrics
    assert d.status == "EXPERIMENTAL"
    assert m["beats_baseline"] is True and o.model_brier < o.best_baseline_brier
    assert o.n_evaluated >= 500                          # min_sample_size passe (multi-saisons)
    blockers = {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}
    assert "positive_clv" in blockers                     # honnêtement bloqué (pas de CLV/live)


def test_no_future_leakage():
    games, _ = load_nfl_games()
    ordered = sorted(games, key=lambda g: g.tipoff)
    mid = ordered[len(ordered) // 2]
    run1 = run_pairwise_elo(games, NFL_PARAMS)
    flipped = (0, 40) if mid.outcome == "home" else (40, 0)
    modified = [replace(g, home_score=flipped[0], away_score=flipped[1]) if g.game_id == mid.game_id else g
                for g in games]
    run2 = run_pairwise_elo(modified, NFL_PARAMS)
    t = {g.game_id: g.tipoff for g in games}
    idx2 = {gid: i for i, gid in enumerate(run2.predicted_game_ids)}
    checked = 0
    for gid, (prob, _) in zip(run1.predicted_game_ids, run1.model_predictions):
        if t[gid] < mid.tipoff:
            assert run2.model_predictions[idx2[gid]][0] == prob
            checked += 1
    assert checked > 50


def test_deterministic():
    a1, a2 = assess_nfl(), assess_nfl()
    assert a1.observations.model_brier == a2.observations.model_brier
