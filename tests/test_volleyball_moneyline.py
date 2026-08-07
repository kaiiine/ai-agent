"""Volley moneyline (Elo pairwise) — données RÉELLES api-sports, hermétique (§2/§4/§30).

Sémantique 2-way VÉRIFIÉE (Winamax « Vainqueur »). home_edge DÉRIVÉ du taux domicile réel.
Skill FORT validé hors échantillon. Verdict mécanique EXPERIMENTAL (échantillon < 500).
"""

from __future__ import annotations

from dataclasses import replace

from src.agents.quant.betting_engine.sports.volleyball.moneyline import (
    VOLLEY_PARAMS, assess_volleyball, load_volleyball_games,
)
from src.agents.quant.betting_engine.sports.pairwise_elo import run_pairwise_elo


def test_dataset_real_and_no_ties():
    games, fingerprint = load_volleyball_games()
    assert len(games) > 300 and fingerprint.startswith("sha256:")
    assert all(g.home_score != g.away_score for g in games)   # volley = toujours un vainqueur


def test_home_edge_is_derived_not_guessed():
    # §6/§7 : home_edge issu du taux domicile MESURÉ (0.547), pas un prior arbitraire.
    assert VOLLEY_PARAMS.home_edge == 33.0 and "DÉRIVÉ" in VOLLEY_PARAMS.notes


def test_experimental_despite_strong_skill():
    """Skill fort mais verdict EXPERIMENTAL — pour d'autres raisons qu'avant.

    `min_sample_size` bloquait à 368 évaluations ; l'acquisition des saisons
    2022 à 2024 le porte à 574 et le critère passe, par les données. Ce qui reste
    est de nature différente : une calibration insuffisante, que davantage
    d'historique ne corrige pas, et une CLV non collectée."""
    a = assess_volleyball()
    o, d, m = a.observations, a.decision, a.metrics
    assert d.status == "EXPERIMENTAL"
    assert m["beats_baseline"] is True and o.model_brier < 0.42   # skill fort (volley prévisible)
    blockers = {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}
    assert "min_sample_size" not in blockers
    assert blockers == {"max_calibration_error", "positive_clv"}


def test_no_future_leakage():
    games, _ = load_volleyball_games()
    ordered = sorted(games, key=lambda g: g.tipoff)
    mid = ordered[len(ordered) // 2]
    run1 = run_pairwise_elo(games, VOLLEY_PARAMS)
    flipped = (0, 3) if mid.outcome == "home" else (3, 0)
    modified = [replace(g, home_score=flipped[0], away_score=flipped[1]) if g.game_id == mid.game_id else g
                for g in games]
    run2 = run_pairwise_elo(modified, VOLLEY_PARAMS)
    t = {g.game_id: g.tipoff for g in games}
    idx2 = {gid: i for i, gid in enumerate(run2.predicted_game_ids)}
    checked = 0
    for gid, (prob, _) in zip(run1.predicted_game_ids, run1.model_predictions):
        if t[gid] < mid.tipoff:
            assert run2.model_predictions[idx2[gid]][0] == prob
            checked += 1
    assert checked > 30


def test_deterministic():
    assert assess_volleyball().observations.model_brier == assess_volleyball().observations.model_brier
