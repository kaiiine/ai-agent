"""Loader dataset tennis (Unité B §1/§2) — source LOCALE explicite, zéro téléchargement.

Données de test SYNTHÉTIQUES au SCHÉMA Sackmann réel (jamais présentées comme réelles).
Prouve : provenance + checksum ; période réelle ; taux de manquants ; séparation
point-in-time (pré-match vs post-match) ; refus explicite si répertoire absent/vide
(aucun repli téléchargé).
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.sports.tennis.dataset_loader import (
    POST_MATCH_FIELDS,
    PRE_MATCH_FIELDS,
    load_sackmann_dir,
)
from src.agents.quant.betting_engine.sports.tennis.inventory import inventory

# En-tête = colonnes RÉELLES Sackmann (sous-ensemble suffisant). Valeurs SYNTHÉTIQUES.
_HEADER = ("tourney_id,tourney_name,surface,tourney_level,tourney_date,"
           "winner_id,winner_name,winner_rank,winner_rank_points,"
           "loser_id,loser_name,loser_rank,loser_rank_points,score,best_of,round,minutes")
_ROWS = [
    "2024-580,Test Open,Hard,A,20240108,101,Player One,5,4000,202,Player Two,40,1100,6-4 6-3,3,R32,95",
    "2024-520,Test Masters,Clay,M,20240210,202,Player Two,38,1200,303,Player Three,60,800,7-6 6-4,3,QF,120",
    # surface + loser_rank manquants -> pré-match INCOMPLET, taux de manquants > 0
    "2024-999,Test Slam,,G,20240601,101,Player One,5,4000,404,Player Four,,600,6-3 6-4 6-2,5,R16,150",
    # date invalide -> ligne IGNORÉE (jamais fabriquée)
    "2024-000,Bad,Hard,A,NOTADATE,1,X,1,10,2,Y,2,20,6-0,3,F,60",
]


def _write(tmp_path, tour="atp"):
    (tmp_path / f"{tour}_matches_2024.csv").write_text("\n".join([_HEADER, *_ROWS]), encoding="utf-8")
    return tmp_path


def test_loads_local_dir_with_provenance_and_checksum(tmp_path):
    ds = load_sackmann_dir(_write(tmp_path), "atp")
    assert ds.tour == "atp" and ds.n == 3                    # ligne à date invalide ignorée
    assert len(ds.files) == 1 and ds.files[0].checksum.startswith("sha256:")
    assert ds.files[0].rows == 3
    assert ds.period[0].isoformat() == "2024-01-08"          # première date de tournoi
    assert ds.period[1].isoformat() == "2024-06-01"          # période RÉELLE couverte (triée)


def test_inventory_reports_missing_rates_and_distributions(tmp_path):
    inv = inventory(load_sackmann_dir(_write(tmp_path), "atp"))
    assert inv["n_matches"] == 3
    assert inv["surface_dist"].get("Hard") == 1 and inv["surface_dist"].get("Clay") == 1
    assert inv["best_of_dist"].get(3) == 2 and inv["best_of_dist"].get(5) == 1
    assert inv["missing_rate"]["surface"] > 0                # 1/3 surface manquante
    assert inv["missing_rate"]["p2_rank"] > 0                # 1/3 loser_rank manquant
    assert inv["pre_match_complete_rate"] == round(2 / 3, 4)  # 2 matchs pré-match complets


def test_point_in_time_separation_is_explicit():
    # L'issue (winner/loser), le score, les stats de service ne sont JAMAIS des features.
    assert "outcome" in POST_MATCH_FIELDS and "score" in POST_MATCH_FIELDS
    assert "outcome" not in PRE_MATCH_FIELDS and "score" not in PRE_MATCH_FIELDS
    # Les classements pré-tournoi SONT pré-match (features admissibles, symétriques).
    assert "p1_rank" in PRE_MATCH_FIELDS and "p2_rank" in PRE_MATCH_FIELDS
    assert "surface" in PRE_MATCH_FIELDS and "best_of" in PRE_MATCH_FIELDS


def test_missing_dir_and_empty_dir_raise_never_download(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sackmann_dir(tmp_path / "does_not_exist", "atp")
    with pytest.raises(ValueError, match="aucun fichier"):
        load_sackmann_dir(tmp_path, "wta")                   # dir existe mais aucun wta_matches_*.csv
