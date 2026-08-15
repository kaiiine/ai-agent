"""Props NFL : des modèles validés, un marché qui n'existe pas encore.

Trente-trois lignes ont été confrontées à l'historique par la MÊME mécanique que
tout le reste du système. Vingt-deux passent. Aucune ne price, et ce n'est pas le
modèle qui bloque — c'est le catalogue.
"""

from __future__ import annotations

import pytest


# ══ NFL : les modèles existent, le marché non ══════════════════════════════
def test_les_familles_nfl_validees_sont_celles_que_la_mesure_a_rendues():
    """Vingt-deux lignes sur trente-trois passent les deux critères. Le motif est
    régulier : la calibration se dégrade PRÈS DE LA MÉDIANE, là où la loi est la
    plus raide — et c'est précisément la région que le bookmaker cote."""
    from src.agents.quant.betting_engine.sports.american_football.props_validation import (
        MESURES, lignes_validees, resume_par_famille,
    )

    assert len(MESURES) == 33
    assert len(lignes_validees()) == 22

    par_famille = resume_par_famille()
    # Volumes : fortement auto-corrélés, toutes les lignes passent.
    for famille in ("RUSHING_YARDS", "RUSHING_ATTEMPTS", "RECEPTIONS"):
        detail = par_famille[famille]
        assert detail["lignes_validees"] == detail["lignes_mesurees"], famille
    # Comptages rares : le modèle ne bat pas la fréquence historique.
    for famille in ("INTERCEPTIONS", "RECEIVING_TDS"):
        assert par_famille[famille]["lignes_validees"] == 0, famille
        assert par_famille[famille]["sans_competence"] > 0, famille


def test_la_calibration_se_degrade_pres_de_la_mediane():
    """Ce n'est pas que le modèle « marche mieux » aux extrêmes : ce sont les
    extrêmes qui pardonnent. Autour de la médiane, une petite erreur de moyenne
    devient une grande erreur de probabilité."""
    from src.agents.quant.betting_engine.sports.american_football.props_validation import (
        MESURES,
    )

    yards = sorted((m for m in MESURES if m.famille == "PASSING_YARDS"),
                   key=lambda m: m.ligne)
    # Médiane observée : 208 yards. Les deux lignes qui l'encadrent sont les
    # deux seules mal calibrées de la famille.
    assert not yards[1].calibre and not yards[2].calibre       # 199,5 et 249,5
    assert yards[0].calibre and yards[3].calibre               # 149,5 et 299,5


def test_aucune_prop_nfl_ne_price_faute_de_marche():
    """Un modèle validé pour un marché qui n'existe pas ne couvre rien. Mesuré :
    16 événements, 514 marchés lus, zéro prop."""
    from src.agents.quant.betting_engine.sports.american_football.props_validation import (
        MARCHE_OBSERVE, STOP_MARCHE,
    )

    assert MARCHE_OBSERVE["props_observees"] == 0
    assert MARCHE_OBSERVE["evenements_nfl"] == 16
    assert STOP_MARCHE.startswith("STOP EXTERNAL")


def test_la_source_joueur_est_enregistree_mais_non_routable():
    """Enregistrée avec sa provenance complète — et NON routable, parce que
    l'axe identité n'a pas pu être mesuré : le catalogue n'expose aucune prop
    NFL, donc aucun nom Winamax à rapprocher d'un `player_id` nflverse."""
    from src.agents.quant.historical_discovery.registry import registre_par_defaut

    source = next(c for c in registre_par_defaut().all()
                  if c.provider == "nflverse_player_stats")

    assert source.classification.licence_id == "CC-BY-4.0"
    assert source.entity_types == ("player",)
    assert source.detail["lignes"] == 134470
    assert not source.is_routable          # identité non mesurable aujourd'hui
