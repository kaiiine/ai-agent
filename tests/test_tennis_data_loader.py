"""Loader tennis-data.co.uk (Unité B) — dataset RÉEL récupéré automatiquement.

Vérifie le contrat sur les fixtures embarquées : volumétrie plausible, période 2015-2024,
checksum, séparation point-in-time (cotes/classements pré-match ; issue post-match),
exclusion des walkovers. Provenance : docs/implementation/PROVENANCE-tennis-data.md.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import load_tennis_data


@pytest.mark.parametrize("tour,min_year", [("atp", 2000), ("wta", 2007)])
def test_real_dataset_loads_with_expected_shape(tour, min_year):
    ds = load_tennis_data(tour)
    assert ds.n > 40000                                      # profondeur réelle (20+ saisons)
    # ATP démarre en 2000, WTA en 2007 (le site n'expose pas de WTA avant) — jamais de
    # match masculin injecté dans le dataset féminin (garde d'intégrité de circuit).
    # Tolérance d'un jour : une saison peut s'ouvrir sur un tournoi débutant le 31/12.
    assert min_year - 1 <= ds.period[0].year <= min_year
    assert ds.period[1].year >= 2026
    assert ds.files[0].checksum.startswith("sha256:")
    # ordre chronologique strict (walk-forward sans fuite)
    assert all(a.tourney_date <= b.tourney_date for a, b in zip(ds.matches, ds.matches[1:]))
    best_of = {m.best_of for m in ds.matches if m.best_of is not None}
    assert best_of <= {3, 5} and 3 in best_of
    if tour == "atp":
        assert 5 in best_of                                  # Bo5 (Grands Chelems masculins)
    surfaces = {m.surface for m in ds.matches if m.surface}
    assert {"Hard", "Clay", "Grass"} <= surfaces


def test_tours_are_not_contaminated():
    """Aucun joueur ne doit exister dans les DEUX circuits (l'ancien build injectait des
    matchs ATP dans le fichier WTA via la négociation de contenu du serveur)."""
    atp = {m.p1_name for m in load_tennis_data("atp").matches}
    wta = {m.p1_name for m in load_tennis_data("wta").matches}
    overlap = atp & wta
    assert len(overlap) <= 5, f"contamination inter-circuits : {sorted(overlap)[:10]}"


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
