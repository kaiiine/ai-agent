"""La matrice des props : ce qu'on sait, et surtout ce qu'on ne sait pas.

Ces tests ne vérifient aucun modèle — il n'y en a aucun. Ils vérifient que la
matrice reste HONNÊTE : qu'une source utilisable ne suffise pas à déclarer une
famille exploitable, et qu'aucune case ne se remplisse d'optimisme.
"""

from __future__ import annotations

import pytest

from src.agents.quant.historical_discovery.player_props import (
    FORBIDDEN,
    FREE_USABLE,
    MATRICE,
    NO_CANDIDATE,
    PAID,
    exploitables,
    par_sport,
    resume,
)


def test_une_source_libre_ne_suffit_pas_a_rendre_une_famille_exploitable():
    """Le NFL a la seule source de props sous licence permissive du système —
    et aucune de ses familles n'est encore modélisable, faute de marché observé.
    Inversement, le basket a 545 marchés et aucune source."""
    libres = [f for f in MATRICE if f.statut == FREE_USABLE]
    assert libres, "nflverse doit apparaître comme source libre"
    assert all(f.sport == "american_football" for f in libres)
    assert all(f.marches_observes == 0 for f in libres)


def test_un_joueur_non_identifiable_bloque_meme_avec_des_donnees():
    """Le blocage le plus dur n'est pas la licence : c'est de ne pas savoir de
    QUI parle le marché. « variant=pre:playerprops:66299338:2601927 » n'expose
    aucun identifiant de joueur résoluble."""
    opaques = [f for f in MATRICE if not f.sujet_identifiable]
    assert opaques
    assert all(not f.exploitable for f in opaques)


def test_le_hockey_est_ferme_contractuellement_pas_techniquement():
    """« HTTP 200 » n'est pas une permission."""
    hockey = par_sport("hockey")
    assert hockey and all(f.statut == FORBIDDEN for f in hockey)
    assert all("spidering" in f.preuve for f in hockey)


def test_le_basket_a_le_marche_et_pas_les_donnees():
    """67,9 % des marchés d'une rencontre de basket sont des props de joueur, et
    le box score par joueur n'est PAS dans le tier gratuit de la seule source
    candidate — il est à 9,99 $/mois et par sport. Une clé gratuite ne
    débloquerait rien : il n'y a pas de credential à demander."""
    basket = par_sport("basketball")
    assert sum(f.marches_observes or 0 for f in basket) >= 490
    assert all(f.statut == PAID for f in basket)
    assert any("Game Player Stats" in f.preuve for f in basket)
    assert not any(f.exploitable for f in basket)


def test_une_seule_branche_est_ouverte_et_c_est_le_NFL():
    """La discovery ne rend pas zéro : elle rend UNE branche, et pas celle qu'on
    attendait. Le NFL a des données de joueur sous CC-BY-4.0 et un sujet
    parfaitement identifiable — mais aucun marché observé au catalogue. Le basket
    a l'inverse exact : 545 marchés et aucune source.

    Dire « rien n'est exploitable » aurait été plus simple et faux : ce qui
    manque au NFL est une observation de marché, pas une donnée."""
    ouvertes = exploitables()

    assert ouvertes, "nflverse ouvre bien une branche"
    assert {f.sport for f in ouvertes} == {"american_football"}
    assert all(f.marches_observes == 0 for f in ouvertes), (
        "le blocage NFL est le MARCHÉ, pas la donnée")


def test_une_famille_attendue_mais_non_observee_n_est_pas_un_zero():
    """`None` et `0` ne disent pas la même chose : l'un veut dire « je n'ai pas
    regardé ce marché », l'autre « je l'ai cherché et il n'y était pas »."""
    non_observees = [f for f in MATRICE if f.marches_observes is None]
    assert non_observees
    assert all("NON observ" in f.preuve for f in non_observees)


def test_le_resume_couvre_toute_la_matrice():
    assert sum(resume().values()) == len(MATRICE)
    assert NO_CANDIDATE in resume()


@pytest.mark.parametrize("famille", MATRICE, ids=lambda f: f"{f.sport}:{f.famille}")
def test_chaque_case_porte_sa_preuve_et_son_blocage(famille):
    """Une case sans preuve est une opinion ; une case sans blocage est une
    promesse. Ni l'une ni l'autre ne se relit dans six mois."""
    assert famille.preuve.strip(), famille
    assert famille.blocage.strip(), famille
    assert famille.donnees_requises, famille
