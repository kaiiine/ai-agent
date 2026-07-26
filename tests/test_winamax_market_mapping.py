"""Mapping libellés Winamax -> vocabulaire canonique (market_mapping.py)."""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.bookmakers.protocol import MarketType
from src.agents.quant.betting_engine.bookmakers.winamax import market_mapping as mm


@pytest.mark.parametrize(
    "name,template,expected",
    [
        ("Résultat", "3way", MarketType.MATCH_WINNER),    # foot / rugby XIII 1X2
        ("Résultat", "2way", MarketType.MATCH_WINNER),    # baseball
        ("Vainqueur", "2way", MarketType.MATCH_WINNER),   # tennis / baseball
        ("Vainqueur", "ListOdd", MarketType.OUTRIGHT_WINNER),  # F1 / cyclisme
        ("Total de buts", "2way", MarketType.UNMAPPED),   # marché non couvert -> jamais deviné
        ("", "", MarketType.UNMAPPED),
    ],
)
def test_map_market(name, template, expected):
    assert mm.map_market(name, template) == expected


def test_listodd_is_always_outright():
    # Tout template ListOdd est une liste de vainqueurs, même libellé inattendu.
    assert mm.map_market("Vainqueur du tournoi", "ListOdd") == MarketType.OUTRIGHT_WINNER


@pytest.mark.parametrize(
    "code,expected",
    [("1", "slot_1"), ("2", "slot_2"), ("x", "draw"), ("X", "draw"),
     (" 1 ", "slot_1"), ("", "UNMAPPED"), ("zz", "UNMAPPED")],
)
def test_map_selection_code_returns_slots_not_roles(code, expected):
    # Le mapping renvoie des SLOTS, jamais home/away : la sémantique de rôle est
    # ajoutée plus tard par le ParticipantRoleResolver.
    assert mm.map_selection_code(code) == expected
