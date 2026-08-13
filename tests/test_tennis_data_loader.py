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
    """La borne d'ouverture porte sur le corpus tennis-data.co.uk LUI-MÊME.

    Le backfill Challenger remonte à 1991 : mesurée sur le corpus complet, cette
    borne dirait seulement que du contexte plus ancien a été ajouté, ce qui est
    voulu. Ce qu'elle doit continuer de garantir, c'est qu'aucun match masculin
    n'a été injecté dans le fichier féminin — donc on la vérifie à la source.
    """
    ds = load_tennis_data(tour, avec_backfill=False)
    assert ds.n > 40000                                      # profondeur réelle (20+ saisons)
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


def test_le_corpus_complet_reste_chronologique():
    """Le backfill s'insère DANS l'ordre, sans quoi le walk-forward fuiterait."""
    ds = load_tennis_data("atp")
    assert all(a.tourney_date <= b.tourney_date
               for a, b in zip(ds.matches, ds.matches[1:]))


def test_tours_are_not_contaminated():
    """Aucun match masculin dans le fichier féminin (l'ancien build en injectait
    via la négociation de contenu du serveur).

    Le contrôle porte sur les FICHIERS tennis-data, seuls concernés par ce défaut.
    Sur le corpus complet il ne prouverait plus rien : le backfill ajoute 18 000
    joueurs ATP, et des patronymes courants comme « Sanchez M. » finissent par
    exister des deux côtés sans qu'aucune rencontre ne se soit déplacée.
    """
    atp = {m.p1_name for m in load_tennis_data("atp", avec_backfill=False).matches}
    wta = {m.p1_name for m in load_tennis_data("wta", avec_backfill=False).matches}
    overlap = atp & wta
    assert len(overlap) <= 5, f"contamination inter-circuits : {sorted(overlap)[:10]}"


def test_le_corpus_d_origine_reste_atteignable_pour_chaque_circuit():
    """`avec_backfill=False` est la seule façon de remesurer l'écart sans refaire
    le pipeline. Il ne doit jamais contenir la moindre rencontre de backfill."""
    for tour in ("atp", "wta"):
        sans = load_tennis_data(tour, avec_backfill=False)
        avec = load_tennis_data(tour)
        assert all(m.circuit is None for m in sans.matches), tour
        assert avec.n > sans.n, tour
        assert len(avec.files) == 2 and len(sans.files) == 1, tour


def test_le_backfill_n_est_jamais_une_cible_d_evaluation():
    """Le contexte construit la force d'un joueur ; il ne devient pas une
    rencontre à prédire. Sinon le dénominateur de la couverture compterait des
    matchs sur lesquels AXON ne parie pas."""
    ds = load_tennis_data("atp")
    contexte = [m for m in ds.matches if m.circuit is not None]
    assert contexte, "le backfill ATP doit être chargé"
    assert not any(m.est_cible_d_evaluation for m in contexte)
    assert all(m.est_cible_d_evaluation for m in ds.matches if m.circuit is None)


def test_les_futures_restent_hors_du_corpus_charge():
    """Décision MESURÉE (ΔBrier 6× pire pour 2 points de couverture) — et
    réversible : les Futures sont dans la fixture, écartés au chargement."""
    from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import (
        CIRCUITS_RETENUS)

    ds = load_tennis_data("atp")
    assert "futures" not in CIRCUITS_RETENUS
    assert not any(m.circuit == "futures" for m in ds.matches)


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
