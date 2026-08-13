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
        # Sans le drapeau `isOutright` de la source, une liste ne prouve rien.
        ("Vainqueur", "ListOdd", MarketType.UNMAPPED),
        ("Total de buts", "2way", MarketType.UNMAPPED),   # marché non couvert -> jamais deviné
        ("", "", MarketType.UNMAPPED),
    ],
)
def test_map_market(name, template, expected):
    assert mm.map_market(name, template) == expected


def test_le_vainqueur_d_epreuve_exige_le_drapeau_de_la_source():
    """`Vainqueur` + `ListOdd` + événement DÉCLARÉ outright : les trois ensemble."""
    assert mm.map_market("Vainqueur", "ListOdd", is_outright=True) == MarketType.OUTRIGHT_WINNER
    assert mm.map_market("Vainqueur", "ListOdd", is_outright=False) == MarketType.UNMAPPED


def test_le_template_listodd_seul_ne_prouve_aucune_famille():
    """L'ancienne règle — TOUT `ListOdd` est un vainqueur d'épreuve — est INFIRMÉE
    par la capture réelle : sur 1 263 marchés `ListOdd` observés, 33 sont des
    vainqueurs d'épreuve. Les autres sont des marqueurs, des « Résultat et nombre
    de buts », des « Mi-temps/Fin de match », des listes de props joueurs.

    Les libellés ci-dessous viennent tous de la capture, et aucun ne désigne le
    vainqueur d'une épreuve — même sur un événement outright, où l'on trouve
    aussi des marchés annexes."""
    for libelle in ("Résultat et nombre de buts", "Mi-temps/Fin de match",
                    "Marqueur d'essai", "Double chance marqueur d'essais"):
        assert mm.map_market(libelle, "ListOdd") == MarketType.UNMAPPED
        assert mm.map_market(libelle, "ListOdd", is_outright=True) == MarketType.UNMAPPED


@pytest.mark.parametrize(
    "code,expected",
    [("1", "slot_1"), ("2", "slot_2"), ("x", "draw"), ("X", "draw"),
     (" 1 ", "slot_1"), ("", "UNMAPPED"), ("zz", "UNMAPPED")],
)
def test_map_selection_code_returns_slots_not_roles(code, expected):
    # Le mapping renvoie des SLOTS, jamais home/away : la sémantique de rôle est
    # ajoutée plus tard par le ParticipantRoleResolver.
    assert mm.map_selection_code(code) == expected
