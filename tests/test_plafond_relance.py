"""Le plafond de relance doit suivre la taille du plan.

Deux relances ne bornent pas la même chose selon ce qu'elles bornent. Vécu sur
un plan de quinze étapes : AXON cédait après 13 % du travail et le modèle
annonçait avoir terminé.

Ce plafond avait été écrit le 2 septembre, puis emporté par le revert du
chantier notebook — il n'avait pourtant rien de spécifique aux notebooks. Le
symptôme est revenu tel quel : « il ne loop pas ».
"""
from __future__ import annotations

import pytest

from src.agents.coding.specialist import (
    _RELANCES_MAX, _RELANCES_PAR_ETAPE, _plafond_de_relance,
)


class _Etape:
    done = False


@pytest.mark.parametrize("etapes, attendu", [(0, 2), (1, 2), (3, 6), (4, 8)])
def test_le_plafond_suit_le_plan(etapes, attendu):
    assert _plafond_de_relance([_Etape()] * etapes) == attendu


def test_un_plan_long_obtient_plus_de_relances():
    """Le cas qui a motivé le correctif."""
    assert _plafond_de_relance([_Etape()] * 15) > _plafond_de_relance([_Etape()] * 3)


def test_le_plafond_reste_borne():
    """Insister sans fin n'est pas un progrès."""
    assert _plafond_de_relance([_Etape()] * 500) == _RELANCES_MAX


def test_un_plan_vide_garde_un_minimum():
    """Sans plan, le comportement d'avant : deux relances."""
    assert _plafond_de_relance([]) == 2


def test_les_constantes_restent_dans_leur_plage():
    """Un plafond à zéro rendrait la relance muette sans que rien ne le dise."""
    assert _RELANCES_PAR_ETAPE >= 1
    assert 5 <= _RELANCES_MAX <= 50
