"""Basket NBA moneyline (Elo) — données RÉELLES api-sports, hermétique (§6/§17/§23).

Prouve : famille statistique PROPRE au basket (jamais Dixon-Coles), walk-forward SANS
FUITE (une info future ne change pas une prédiction antérieure), verdict MÉCANIQUE
EXPERIMENTAL (jamais un faux SUPPORTED), déterminisme, issue 2-way correcte.
"""

from __future__ import annotations

import inspect
from dataclasses import replace

from src.agents.quant.betting_engine.sports.basketball import moneyline as M
from src.agents.quant.betting_engine.sports.basketball.moneyline import (
    assess_nba, load_nba_games, run_elo_walk_forward, _p_home,
)


def test_dataset_is_real_and_loaded():
    """Trois saisons NBA acquises (2022-23 à 2024-25). On vérifie un PLANCHER et
    les invariants du sport, pas un compte exact : figer la taille ferait échouer
    le test à chaque acquisition sans jamais détecter une donnée corrompue."""
    games, fingerprint = load_nba_games()
    assert len(games) >= 1386                                # jamais de régression
    assert fingerprint.startswith("sha256:")
    assert all(g.home_points != g.away_points for g in games)   # pas de nul en NBA
    assert len({g.game_id for g in games}) == len(games)        # aucun doublon d'acquisition
    assert games == sorted(games, key=lambda g: g.tipoff)       # ordre chronologique


def test_no_dixon_coles_or_football_reuse():
    # §0 : jamais réutiliser une hypothèse football pour un autre sport.
    src = inspect.getsource(M)
    for banned in ("dixon_coles", "OneXTwoModel", "goals_home", "one_x_two"):
        assert banned not in src, f"réutilisation football interdite : {banned}"


def test_elo_probability_is_valid_and_symmetric():
    p = _p_home(1600.0, 1500.0)
    assert 0.0 < p < 1.0
    assert _p_home(1500.0, 1500.0) > 0.5              # avantage domicile (HOME_EDGE > 0)
    # symétrie : P_home(a,b) + P_home(b,a) tient compte du home edge des deux côtés
    assert abs(_p_home(1500.0, 1700.0) + _p_home(1700.0, 1500.0) - 1.0) < 0.25


def test_walk_forward_has_no_future_leakage():
    # §17 OBLIGATOIRE : modifier fortement un match FUTUR ne change AUCUNE prédiction
    # antérieure (l'Elo ne dépend que des matchs strictement passés).
    games, _ = load_nba_games()
    ordered = sorted(games, key=lambda g: g.tipoff)
    mid = ordered[len(ordered) // 2]
    id_to_time = {g.game_id: g.tipoff for g in games}

    run1 = run_elo_walk_forward(games)
    # Résultat du match médian rendu extrême et OPPOSÉ à l'issue réelle.
    flipped = (0, 200) if mid.outcome == "home" else (200, 0)
    modified = [replace(g, home_points=flipped[0], away_points=flipped[1])
                if g.game_id == mid.game_id else g for g in games]
    run2 = run_elo_walk_forward(modified)

    idx2 = {gid: i for i, gid in enumerate(run2.predicted_game_ids)}
    checked = 0
    for gid, (prob, _) in zip(run1.predicted_game_ids, run1.model_predictions):
        if id_to_time[gid] < mid.tipoff:                 # match antérieur au match modifié
            assert run2.model_predictions[idx2[gid]][0] == prob   # prédiction INCHANGÉE
            checked += 1
    assert checked > 100                                 # a réellement vérifié beaucoup d'antérieurs


def test_assessment_is_experimental_and_beats_baseline():
    a = assess_nba()
    o, d, m = a.observations, a.decision, a.metrics
    assert d.status == "EXPERIMENTAL"                    # mécanique, jamais SUPPORTED
    assert o.n_evaluated > 1000 and o.n_temporal_folds >= 3
    assert m["beats_baseline"] is True                   # Brier modèle < baseline (skill réel)
    assert o.model_brier < o.best_baseline_brier
    # `measurable_live_freshness` est un bloqueur RÉEL : la Gateway n'a de chaîne
    # de providers que pour le football, donc aucune fraîcheur ne peut être
    # horodatée au point de décision pour ce sport. Ce test affirmait le
    # contraire — il verrouillait un PASS que le chemin de décision ne pouvait
    # pas honorer, et qui ne tenait qu'à une constante écrite dans l'évaluateur.
    blockers = {c.name for c in d.criteria if c.required and c.verdict.value != "PASS"}
    assert "positive_clv" in blockers
    assert "measurable_live_freshness" in blockers


def test_assessment_is_deterministic():
    a1, a2 = assess_nba(), assess_nba()
    assert a1.decision.status == a2.decision.status
    assert a1.observations.n_evaluated == a2.observations.n_evaluated
    assert a1.observations.model_brier == a2.observations.model_brier
