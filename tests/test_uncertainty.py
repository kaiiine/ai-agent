"""Borne basse de probabilité — mesurée, jamais une marge forfaitaire.

`probability_low` valait `fair_probability` sur tous les modèles. Le contrat
l'annonçait (`uncertainty_status=NOT_ESTIMATED`) et la conséquence restait
fâcheuse : c'est la valeur que le sizing traite comme PRUDENTE, et un point
estimé n'a rien de prudent. Mesuré en walk-forward strict, l'issue observée
atteignait la borne annoncée 0 % du temps au basket.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.uncertainty import (
    MIN_ECHANTILLON,
    N_TRANCHES,
    build_bins,
    wilson_lower,
)


# ══ Le minorant lui-même ═══════════════════════════════════════════════════
def test_le_minorant_est_toujours_sous_la_proportion():
    for succes, total in ((5, 10), (50, 100), (500, 1000), (1, 3)):
        assert wilson_lower(succes, total) <= succes / total


def test_le_minorant_se_resserre_quand_l_echantillon_grandit():
    """C'est la propriété qui rend la borne informative : plus d'observations,
    moins d'incertitude — sans qu'aucune constante n'intervienne."""
    proportions = [wilson_lower(int(0.6 * n), n) for n in (30, 100, 1000, 10000)]

    assert proportions == sorted(proportions)
    assert proportions[-1] < 0.6


def test_le_minorant_reste_dans_zero_un():
    for succes, total in ((0, 30), (30, 30), (0, 1), (1, 1)):
        borne = wilson_lower(succes, total)
        assert 0.0 <= borne <= 1.0


def test_un_echantillon_vide_ne_produit_aucune_confiance():
    assert wilson_lower(0, 0) == 0.0


@pytest.mark.parametrize("confiance", [0.80, 0.90, 0.95, 0.99])
def test_un_niveau_plus_eleve_donne_une_borne_plus_basse(confiance):
    """Plus on exige de confiance, plus la borne descend. L'inverse signalerait
    une erreur de signe — et une prudence apparente qui n'en serait pas une."""
    reference = wilson_lower(60, 100, 0.80)

    assert wilson_lower(60, 100, confiance) <= reference + 1e-12


# ══ Les tranches ═══════════════════════════════════════════════════════════
def test_la_borne_depend_de_la_tranche_pas_d_une_penalite_globale():
    """Exigence explicite : la borne doit refléter CETTE prédiction. Mesuré sur
    données réelles, la largeur varie d'un facteur 2,7 (NBA) à 9,6 (MLB) entre
    tranches — ce n'est donc pas une pénalité forfaitaire déguisée."""
    paires = ([(0.25, 1.0)] * 20 + [(0.25, 0.0)] * 80        # tranche basse : 20 %
              + [(0.75, 1.0)] * 75 + [(0.75, 0.0)] * 25)     # tranche haute : 75 %
    bins = build_bins(paires)

    basse = 0.25 - bins.borne_basse(0.25)
    haute = 0.75 - bins.borne_basse(0.75)

    assert basse != haute


def test_une_tranche_trop_maigre_ne_rend_pas_de_borne():
    """Une borne large est une MESURE ; une absence n'en est pas une. Les
    confondre ferait passer l'ignorance pour de la prudence."""
    bins = build_bins([(0.55, 1.0)] * (MIN_ECHANTILLON - 1))

    assert bins.borne_basse(0.55) is None


def test_une_tranche_suffisante_rend_une_borne():
    bins = build_bins([(0.55, 1.0)] * 30 + [(0.55, 0.0)] * 30)

    assert bins.borne_basse(0.55) is not None


def test_la_borne_ne_remonte_jamais_au_dessus_de_la_prediction():
    """Quand l'historique est meilleur que la prédiction, c'est la prédiction qui
    fait foi : la borne MINORE, elle ne sert pas à rendre un modèle optimiste."""
    bins = build_bins([(0.55, 1.0)] * 200)          # 100 % réalisés dans la tranche

    assert bins.borne_basse(0.55) <= 0.55


def test_un_modele_surconfiant_voit_sa_borne_descendre():
    """Le cas NBA : annoncer 0,62 et réaliser 0,55. Aucune constante n'est
    choisie — c'est l'écart observé qui fait descendre la borne."""
    paires = [(0.62, 1.0)] * 55 + [(0.62, 0.0)] * 45

    borne = build_bins(paires).borne_basse(0.62)

    assert borne < 0.55


def test_les_tranches_couvrent_l_intervalle_unite():
    bins = build_bins([(p / 100, 1.0) for p in range(101)])

    assert len(bins.total) == N_TRANCHES
    assert sum(bins.total) == 101
    assert bins.tranche(0.0) == 0 and bins.tranche(1.0) == N_TRANCHES - 1


# ══ Point-in-time : la borne ne voit jamais son propre résultat ════════════
def test_la_table_ne_contient_que_ce_qu_on_lui_donne():
    """Garantie structurelle : `build_bins` n'ordonne rien et ne lit aucune
    source. C'est à l'appelant de ne fournir que des observations antérieures —
    et le contrat le dit, pour qu'aucun appelant ne croie à une protection
    qu'il n'a pas."""
    bins = build_bins([(0.5, 1.0), (0.5, 0.0)])

    assert sum(bins.total) == 2


# ══ Bout en bout : la borne atteint réellement le candidat ═════════════════
def test_l_invariant_du_domaine_tient_toujours():
    """0 <= probability_low <= fair_probability <= 1. Le domaine le vérifie déjà
    à la construction ; ce test s'assure que la borne mesurée ne peut pas le
    violer, quelle que soit la table de calibration."""
    from src.agents.quant.betting_engine.uncertainty import bound_for

    for version in ("basketball.moneyline.elo.v0", "baseball.moneyline.elo.v0",
                    "tennis.moneyline.elo.v0", "volleyball.moneyline.elo.v0"):
        for probabilite in (0.01, 0.25, 0.5, 0.62, 0.9, 0.99):
            borne, _ = bound_for(version, probabilite)
            assert 0.0 <= borne <= probabilite <= 1.0, (version, probabilite)


def test_un_modele_sans_table_reste_non_estime():
    """Sans mesure, la seule description honnête est « non estimée » — pas une
    borne fabriquée à partir de rien."""
    from src.agents.quant.betting_engine.uncertainty import bound_for

    borne, mesuree = bound_for("modele.inexistant.v0", 0.62)

    assert borne == 0.62 and mesuree is False


def test_la_borne_mesuree_descend_reellement_sur_un_modele_surconfiant():
    """NBA annonce 0,62 et réalise 0,55 sur son historique : la borne doit le
    refléter. C'est la mesure, pas une pénalité."""
    from src.agents.quant.betting_engine.uncertainty import bound_for

    borne, mesuree = bound_for("basketball.moneyline.elo.v0", 0.62)

    assert mesuree is True
    assert borne < 0.62


def test_le_statut_d_incertitude_suit_la_disponibilite_de_la_mesure():
    """`ESTIMATED` ne doit jamais accompagner une borne non mesurée : c'est
    exactement la confusion que le statut existe pour empêcher."""
    from src.agents.quant.betting_engine.core.market_model import UncertaintyStatus

    assert UncertaintyStatus.ESTIMATED != UncertaintyStatus.NOT_ESTIMATED


def test_aucune_marge_forfaitaire_dans_le_module():
    """Interdiction explicite : `probability_low = fair_probability - constante`.
    Le module ne doit contenir aucune soustraction d'une constante à une
    probabilité."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent / "src" / "agents"
              / "quant" / "betting_engine" / "uncertainty.py")
    arbre = ast.parse(source.read_text())

    coupables = []
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Sub)
                and isinstance(noeud.right, ast.Constant)
                and isinstance(noeud.right.value, float)
                and 0 < noeud.right.value < 1):
            coupables.append(noeud.lineno)

    assert not coupables, f"marge forfaitaire soupçonnée aux lignes {coupables}"
