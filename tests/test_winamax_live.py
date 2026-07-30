"""Test LIVE Winamax — OPT-IN (§17). Jamais exécuté implicitement en CI : nécessite
`AXON_LIVE=1`. Utilise le VRAI réseau, exige `SOURCE_LIVE`, AUCUN fallback fixture :
si le réseau échoue, le test échoue explicitement (jamais un vert trompeur via replay).
"""

from __future__ import annotations

import os

import pytest

_LIVE = os.environ.get("AXON_LIVE") == "1"


@pytest.mark.skipif(not _LIVE, reason="live opt-in : définir AXON_LIVE=1 (jamais en CI)")
def test_winamax_live_is_source_live_and_multicompetition():
    from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import (
        SOURCE_LIVE,
        capture_live_state,
        replay,
    )
    from src.agents.quant.betting_engine.capability import coverage_matrix

    capture = capture_live_state("football")             # VRAI fetch réseau (lève si échec)
    assert capture.source == SOURCE_LIVE                  # jamais SOURCE_SYNTHETIC
    assert capture.is_authentic is True

    events = replay(capture)
    assert len(events) > 0                                # catalogue réel non vide
    matrix = coverage_matrix(events, "football")
    assert matrix.competitions_discovered > 1            # découverte multi-compétition réelle
    # Distinction observable : découverte large, couverture modèle restreinte + honnête.
    assert matrix.events_discovered >= matrix.events_evaluable
