"""Loader tennis-data.co.uk (Unité B) — dataset RÉEL récupéré automatiquement.

Vérifie le contrat sur les fixtures embarquées : volumétrie plausible, période 2015-2024,
checksum, séparation point-in-time (cotes/classements pré-match ; issue post-match),
exclusion des walkovers. Provenance : docs/implementation/PROVENANCE-tennis-data.md.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import load_tennis_data


@pytest.mark.parametrize("tour,expected_best_of", [("atp", {3, 5}), ("wta", {3})])
def test_real_dataset_loads_with_expected_shape(tour, expected_best_of):
    ds = load_tennis_data(tour)
    assert ds.n > 20000                                      # 10 saisons réelles
    assert ds.period[0].year == 2015 and ds.period[1].year == 2024
    assert ds.files[0].checksum.startswith("sha256:")
    # ordre chronologique strict (walk-forward sans fuite)
    assert all(a.tourney_date <= b.tourney_date for a, b in zip(ds.matches, ds.matches[1:]))
    best_of = {m.best_of for m in ds.matches if m.best_of is not None}
    assert best_of == expected_best_of                      # ATP Bo3+Bo5 ; WTA Bo3 seul
    surfaces = {m.surface for m in ds.matches if m.surface}
    assert {"Hard", "Clay", "Grass"} <= surfaces


def test_point_in_time_fields_present_and_odds_are_pre_match():
    ds = load_tennis_data("atp")
    m = next(x for x in ds.matches if x.p1_rank and x.p2_rank and x.p1_close_odds)
    # PRÉ-MATCH : classements (début de tournoi) + cotes de clôture (« before play starts »).
    assert m.p1_rank and m.p2_rank and m.p1_close_odds and m.p2_close_odds
    # POST-MATCH : l'issue (p1 = vainqueur) — jamais une feature.
    assert m.outcome == "p1"


def test_walkovers_excluded_never_a_game_result():
    ds = load_tennis_data("wta")
    assert all((m.comment or "").lower() != "walkover" for m in ds.matches)
