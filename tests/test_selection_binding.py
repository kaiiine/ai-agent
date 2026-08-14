"""Codes bookmaker -> sélections canoniques. UN seul composant, produit et banc.

Deux implémentations parallèles feraient d'une preuve « ça marche sur les vrais
marchés » une propriété du harness. Ce module est celui que le chemin produit
appelle, et le replay doit appeler le même.

Le principe qui commande tout : on lit les CODES, jamais les libellés. Le
chantier a déjà payé une fois pour l'avoir oublié — « Mi-temps - Vainqueur
(remboursé si match nul) » ne porte la mi-temps que dans son nom.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.markets.selection_binding import (
    ECHEC,
    canonicaliser_selections,
)

DOMICILE_EN_TETE = {"slot_1": "home", "slot_2": "away"}
EXTERIEUR_EN_TETE = {"slot_1": "away", "slot_2": "home"}


def _lier(famille, codes, roles=DOMICILE_EN_TETE):
    return canonicaliser_selections(family=famille, codes=codes, roles=roles)


# ── 1X2, remboursé si nul ────────────────────────────────────────────────────

def test_le_1x2_suit_les_roles_resolus():
    b = _lier(MarketFamily.MATCH_WINNER, ["1", "x", "2"])
    assert b.complete
    assert b.par_code == {"1": "home", "x": "draw", "2": "away"}


def test_le_1x2_s_inverse_quand_slot_1_est_l_exterieur():
    """`slot_1` n'est pas « l'équipe à domicile » : c'est le premier compétiteur
    affiché. Confondre les deux inverse la prédiction."""
    b = _lier(MarketFamily.MATCH_WINNER, ["1", "x", "2"], EXTERIEUR_EN_TETE)
    assert b.par_code == {"1": "away", "x": "draw", "2": "home"}


def test_le_rembourse_si_nul_n_a_que_deux_issues():
    b = _lier(MarketFamily.DRAW_NO_BET, ["1", "2"])
    assert b.par_code == {"1": "home", "2": "away"}


# ── Double chance ────────────────────────────────────────────────────────────

def test_la_double_chance_nomme_ses_unions_par_les_roles():
    b = _lier(MarketFamily.DOUBLE_CHANCE, ["9", "10", "11"])
    assert b.par_code == {"9": "home_or_draw", "10": "home_or_away", "11": "draw_or_away"}


def test_la_double_chance_s_inverse_aussi():
    """Code 9 = « premier compétiteur ou nul ». Si le premier est l'extérieur,
    c'est `draw_or_away` — et l'afficher `home_or_draw` désignerait l'autre
    équipe."""
    b = _lier(MarketFamily.DOUBLE_CHANCE, ["9", "10", "11"], EXTERIEUR_EN_TETE)
    assert b.par_code == {"9": "draw_or_away", "10": "home_or_away", "11": "home_or_draw"}


# ── Plus/Moins ───────────────────────────────────────────────────────────────

def test_le_plus_moins_ne_designe_aucun_competiteur():
    """`over`/`under` sont déjà canoniques : aucun rôle à résoudre, donc rien à
    inverser."""
    for roles in (DOMICILE_EN_TETE, EXTERIEUR_EN_TETE):
        b = _lier(MarketFamily.TOTALS, ["over", "under"], roles)
        assert b.par_code == {"over": "over", "under": "under"}


# ── Score exact ──────────────────────────────────────────────────────────────

def test_le_score_exact_est_retourne_quand_slot_1_est_l_exterieur():
    """« 2:1 » compte 2 pour le PREMIER compétiteur. Si celui-ci joue à
    l'extérieur, la forme canonique domicile:extérieur est « 1:2 » — sans quoi on
    price 2-1 pour 1-2."""
    direct = _lier(MarketFamily.EXACT_SCORE, ["2:1", "0:0", "other"])
    assert direct.par_code == {"2:1": "2:1", "0:0": "0:0", "other": "other"}

    inverse = _lier(MarketFamily.EXACT_SCORE, ["2:1", "0:0", "other"], EXTERIEUR_EN_TETE)
    assert inverse.par_code == {"2:1": "1:2", "0:0": "0:0", "other": "other"}


def test_l_issue_other_traverse_sans_transformation():
    for roles in (DOMICILE_EN_TETE, EXTERIEUR_EN_TETE):
        assert _lier(MarketFamily.EXACT_SCORE, ["other"], roles).par_code == {"other": "other"}


# ── Échec : aucune probabilité sur une issue qu'on ne comprend pas ───────────

@pytest.mark.parametrize("famille,codes", [
    (MarketFamily.MATCH_WINNER, ["1", "zz"]),
    (MarketFamily.DOUBLE_CHANCE, ["9", "42"]),
    (MarketFamily.TOTALS, ["over", "push"]),
    (MarketFamily.EXACT_SCORE, ["2:1", "beaucoup"]),
])
def test_un_code_inconnu_fait_echouer_la_liaison(famille, codes):
    b = _lier(famille, codes)
    assert not b.complete
    assert ECHEC in b.reason
    assert b.canonique(codes[-1]) is None


def test_un_role_manquant_ne_produit_pas_une_supposition():
    """Sans rôle résolu, `slot_1` ne devient pas `home` par défaut."""
    b = _lier(MarketFamily.MATCH_WINNER, ["1", "x", "2"], {})
    assert not b.complete
    assert set(b.non_resolus) == {"1", "2"}
    assert b.par_code == {"x": "draw"}          # le nul ne dépend d'aucun rôle


# ── Les libellés ne sont jamais lus ──────────────────────────────────────────

def test_le_module_ne_lit_aucun_libelle():
    """Un libellé change de langue, d'orthographe et de casse ; un code, non."""
    import ast
    import inspect

    from src.agents.quant.betting_engine.markets import selection_binding

    arbre = ast.parse(inspect.getsource(selection_binding))
    noms = {n.attr for n in ast.walk(arbre) if isinstance(n, ast.Attribute)}
    noms |= {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    for interdit in ("label", "libelle", "bet_type_name", "name"):
        assert interdit not in noms, interdit


def test_le_mapping_de_slot_est_celui_de_la_production():
    """La conversion code -> slot n'est pas réécrite : c'est celle du connecteur,
    déjà en service."""
    import inspect

    from src.agents.quant.betting_engine.markets import selection_binding

    assert "map_selection_code" in inspect.getsource(selection_binding)
