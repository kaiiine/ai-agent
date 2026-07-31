"""Baseball MLB moneyline (Elo pairwise générique) — données RÉELLES, hermétique (§5/§6/§7).

Prouve : recette Elo réutilisée AVEC validation (pas copier-coller), PARAMÈTRES propres
au baseball (jamais ceux du basket), skill VALIDÉ hors échantillon, walk-forward sans
fuite, verdict mécanique EXPERIMENTAL.
"""

from __future__ import annotations

from dataclasses import replace

from src.agents.quant.betting_engine.sports.baseball.moneyline import (
    MLB_PARAMS, assess_mlb, load_mlb_games,
)
from src.agents.quant.betting_engine.sports.basketball.moneyline import K_FACTOR as NBA_K, HOME_EDGE as NBA_HE
from src.agents.quant.betting_engine.sports.pairwise_elo import run_pairwise_elo


def test_dataset_real_and_no_ties():
    games, fingerprint = load_mlb_games()
    assert len(games) > 2000                                 # saison MLB 2022 réelle
    assert fingerprint.startswith("sha256:")
    assert all(g.home_score != g.away_score for g in games)  # pas de nul en MLB


def test_params_are_baseball_specific_not_copied_from_basket():
    # §7 : aucune valeur héritée du basket sans justification.
    assert MLB_PARAMS.k_factor == 4.0 and MLB_PARAMS.k_factor != NBA_K       # K=4 (variance) != 20
    assert MLB_PARAMS.home_edge == 24.0 and MLB_PARAMS.home_edge != NBA_HE   # ~54% != ~60%
    assert MLB_PARAMS.notes                                                   # justification documentée


def test_walk_forward_experimental_and_beats_baseline():
    a = assess_mlb()
    o, d, m = a.observations, a.decision, a.metrics
    assert d.status == "EXPERIMENTAL"                        # mécanique, jamais SUPPORTED
    assert o.n_evaluated > 2000
    assert m["beats_baseline"] is True                       # skill RÉEL mesuré hors échantillon
    assert o.model_brier < o.best_baseline_brier
    blockers = {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}
    assert "positive_clv" in blockers                        # honnêtement bloqué (pas de CLV)


def test_generic_harness_has_no_future_leakage():
    # §17 : modifier un match FUTUR ne change aucune prédiction antérieure (Elo séquentiel).
    games, _ = load_mlb_games()
    ordered = sorted(games, key=lambda g: g.tipoff)
    mid = ordered[len(ordered) // 2]
    t_mid = mid.tipoff
    run1 = run_pairwise_elo(games, MLB_PARAMS)
    flipped = (0, 9) if mid.outcome == "home" else (9, 0)
    modified = [replace(g, home_score=flipped[0], away_score=flipped[1]) if g.game_id == mid.game_id else g
                for g in games]
    run2 = run_pairwise_elo(modified, MLB_PARAMS)
    id_to_time = {g.game_id: g.tipoff for g in games}
    idx2 = {gid: i for i, gid in enumerate(run2.predicted_game_ids)}
    checked = 0
    for gid, (prob, _) in zip(run1.predicted_game_ids, run1.model_predictions):
        if id_to_time[gid] < t_mid:
            assert run2.model_predictions[idx2[gid]][0] == prob
            checked += 1
    assert checked > 200


def test_deterministic():
    a1, a2 = assess_mlb(), assess_mlb()
    assert a1.observations.model_brier == a2.observations.model_brier
    assert a1.decision.status == a2.decision.status
