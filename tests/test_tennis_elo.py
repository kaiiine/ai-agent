"""Tennis Elo surface-aware (Unité B) — skill RÉEL mesuré, sans fuite, EXPERIMENTAL.

Prouve, sur les vraies données ATP/WTA (tennis-data.co.uk) : le modèle bat la baseline
FAVORI-AU-CLASSEMENT hors échantillon, est bien calibré, ne fuit jamais le futur
(étiquetage par ordre canonique), et reste mécaniquement EXPERIMENTAL.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.agents.quant.betting_engine.sports.tennis.elo_model import (
    ATP_PARAMS,
    assess_tennis,
    run_tennis_walk_forward,
)
from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import load_tennis_data


@pytest.mark.parametrize("tour", ["atp", "wta"])
def test_beats_rank_baseline_out_of_sample_and_experimental(tour):
    a = assess_tennis(tour)
    m, o = a.metrics, a.decision
    assert m["beats_rank_baseline"] is True                  # bat le favori-classement (≈0.64), pas 0.5
    assert m["model_brier"] < m["uniform_brier"]
    assert a.observations.n_evaluated > 10000 and a.observations.n_temporal_folds >= 5
    assert a.observations.calibration_error < 0.05           # bien calibré
    assert o.status == "EXPERIMENTAL"                        # jamais un faux SUPPORTED


def test_market_is_reported_as_context_not_a_gate():
    a = assess_tennis("atp")
    # Le marché (cote implicite) est plus fin que le modèle — reporté, jamais un critère.
    assert a.metrics["market_brier"] is not None and a.metrics["market_brier"] < a.metrics["model_brier"]


def test_no_future_leakage_canonical_labeling():
    # Modifier l'issue du DERNIER match ne change AUCUNE prédiction antérieure : les notes
    # ne dépendent que du passé, et l'étiquetage est par ordre de nom (pas de position).
    ds = load_tennis_data("atp")
    games = list(ds.matches)
    base = run_tennis_walk_forward(games, ATP_PARAMS)
    last = games[-1]
    swapped = games[:-1] + [replace(last, p1_name=last.p2_name, p2_name=last.p1_name,
                                    p1_rank=last.p2_rank, p2_rank=last.p1_rank)]
    alt = run_tennis_walk_forward(swapped, ATP_PARAMS)
    assert alt.model_pairs[:-1] == base.model_pairs[:-1]     # tout le passé identique


def test_deterministic():
    assert assess_tennis("wta").metrics["model_brier"] == assess_tennis("wta").metrics["model_brier"]
