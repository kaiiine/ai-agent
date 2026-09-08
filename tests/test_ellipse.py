"""Un tour elliptique se reconnaît à l'absence de signal, pas à sa longueur.

« reprend ou tu en étais sans rien oublier » : huit mots, aucun domaine, et le
routeur y répondait par `shell_ls` — le seul échec SILENCIEUX qui survive à
toutes les exécutions de `outils/mesure_filet.py`. Le test qui existait exigeait
MOINS de huit mots : il ratait pile le cas qu'il devait attraper.

Les seuils ont été choisis sur `ELLIPSES_REGLAGE` / `AUTONOMES_REGLAGE` puis
confrontés SANS RETOUCHE aux jeux tenus à l'écart. Ces tests vérifient les deux,
et l'écart entre eux : c'est lui qui trahit un surajustement, pas le score.
"""
from __future__ import annotations

import pytest

from src.orchestrator.ellipse import _MOTS_MAX, est_une_ellipse, porte_un_signal
from tests.corpus_ellipses import (
    AUTONOMES_REGLAGE, AUTONOMES_TENUES, ELLIPSES_REGLAGE, ELLIPSES_TENUES,
)


def _taux(jeu, attendu: bool) -> float:
    return sum(est_une_ellipse(q) is attendu for q in jeu) / len(jeu)


# ── le cas qui a motivé le chantier ───────────────────────────────────────────
def test_le_cas_de_huit_mots_est_attrape():
    """Le proxy de longueur exigeait `< 8` ; la phrase en fait exactement huit."""
    requete = "reprend ou tu en étais sans rien oublier"

    assert len(requete.split()) == 8
    assert est_une_ellipse(requete)


def test_lautre_ellipse_mesuree_est_attrapee():
    assert est_une_ellipse("contoinue alors, reprend le travail et finin moi tout ça")


# ── ce qui ne doit jamais se déclencher ───────────────────────────────────────
@pytest.mark.parametrize("requete", [
    "quel temps fait-il à Paris ?",
    "envoie le récap dans le salon test-cron sur Slack",
    "https://sketchfab.com/3d-models/7-igloo-6e1362cd",
    "~/.local/bin/fan-max-test",
])
def test_une_requete_qui_porte_son_domaine_nest_pas_une_ellipse(requete):
    assert not est_une_ellipse(requete)


def test_un_faux_positif_connu_reste_connu():
    """« quels sont mes fichiers modifiés ? » se déclenche À TORT : `fichiers`
    n'est dans les `keywords` d'aucun groupe — ils sont volontairement étroits,
    réservés aux termes qui ne désignent rien d'autre.

    Deux vocabulaires plus larges ont été essayés et MESURÉS pires : tous les
    mots des documents de groupe fait tomber le rappel de 9/10 à 6/10 sur le jeu
    tenu à l'écart (« quels », « sont » y figurent), et le filtre par
    distinctivité ne les élimine pas davantage.

    Le coût est nul, mesuré : recoller les tours précédents — même SANS RAPPORT —
    laisse le routage à 14/17 requêtes servies, exactement comme la requête
    seule. Ce test épingle le défaut pour qu'il reste visible plutôt que d'être
    caché par un critère dilué."""
    assert est_une_ellipse("quels sont mes fichiers modifiés ?")


def test_une_requete_vide_nest_pas_une_ellipse():
    """Le premier tour d'une conversation ne doit rien déclencher."""
    assert not est_une_ellipse("")
    assert not est_une_ellipse("   ")


# ── les deux jeux, et surtout leur écart ──────────────────────────────────────
def test_le_rappel_tient_sur_le_jeu_de_reglage():
    assert _taux(ELLIPSES_REGLAGE, True) >= 0.75


def test_le_rappel_tient_sur_le_jeu_TENU_A_LECART():
    """Le chiffre qui compte : ce jeu n'a jamais servi à choisir un seuil."""
    assert _taux(ELLIPSES_TENUES, True) >= 0.75


def test_lecart_entre_les_deux_jeux_reste_petit():
    """Vingt points d'écart, c'est la signature du surajustement — mesurée sur les
    alias de skills, où le jeu de réglage donnait 95,5 % et l'autre 75,0 %."""
    ecart = abs(_taux(ELLIPSES_REGLAGE, True) - _taux(ELLIPSES_TENUES, True))

    assert ecart < 0.20


def test_les_faux_positifs_restent_bornes():
    """Un faux positif recolle les tours précédents. Mesuré au pire cas — des
    tours SANS RAPPORT — le routage reste à 14/17 requêtes servies, identique à
    la requête seule : le coût est nul, mais il ne doit pas devenir la règle."""
    for jeu in (AUTONOMES_REGLAGE, AUTONOMES_TENUES):
        assert _taux(jeu, False) >= 0.75


def test_ce_test_bat_le_proxy_quil_remplace():
    """Sans ça, rien ne dirait que le remplacement valait la peine."""
    ancien = sum(len(q.split()) < 8 for q in ELLIPSES_TENUES)
    nouveau = sum(map(est_une_ellipse, ELLIPSES_TENUES))

    assert nouveau > ancien


# ── le vocabulaire n'est pas une liste écrite pour l'occasion ─────────────────
def test_le_vocabulaire_vient_des_groupes():
    """Une liste de marqueurs curée à la main est ce qui a produit les vingt
    points d'écart sur les skills. Celle-ci est celle des groupes, déjà mesurée,
    et elle bouge avec eux."""
    from src.orchestrator.ellipse import _vocabulaire
    from src.orchestrator.tool_retriever import TOOL_GROUPS

    declares = set()
    for spec in TOOL_GROUPS.values():
        declares |= set(spec.keywords) | set(spec.soft_keywords)

    assert _vocabulaire() == declares
    assert len(declares) > 50


def test_un_signal_de_domaine_est_bien_vu():
    assert porte_un_signal("envoie ça sur Slack")
    assert porte_un_signal("va voir http://exemple.fr")
    assert not porte_un_signal("du coup ?")


def test_le_seuil_de_mots_reste_au_dessus_de_lancien():
    """Descendre sous 8 rendrait le proxy de longueur, en pire."""
    assert _MOTS_MAX > 8
