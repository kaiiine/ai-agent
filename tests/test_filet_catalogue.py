"""Le filet de rattrapage doit exister à chaque tour — c'est vérifiable sans modèle.

AXON ne prédit pas l'outil : il en lie seize sur 105, montre le catalogue complet
et donne `obtenir_outil` pour réclamer ce qui manque. Tout le taux de réussite
réel repose sur cette pièce — mesuré, elle fait passer le routage de 84,7 % au
niveau de l'étage 1 à 93,9 % de ce que le modèle reçoit vraiment.

Une pièce dont tout dépend et que rien ne surveille finit par être désactivée par
accident. Trois choses se cassent en silence :

    le catalogue cesse de nommer un outil        → il devient injoignable
    `obtenir_outil` sort de la sélection          → plus rien à réclamer
    le prompt cesse de dire que la liste est partielle → le modèle improvise

Ces tests ne mesurent PAS si le modèle utilise l'échappatoire — ça demande un
appel réseau, ça dépend du modèle, et ça vit dans `outils/mesure_filet.py`. Ils
garantissent qu'elle est là pour être utilisée.
"""
from __future__ import annotations

import pytest

from src.orchestrator import catalogue
from src.orchestrator.registry import build_all_tools


@pytest.fixture(scope="module")
def outils() -> list:
    return build_all_tools()


@pytest.fixture(scope="module")
def indexe(outils) -> None:
    catalogue.indexer(outils + [catalogue.obtenir_outil])


# ── le catalogue nomme tout ───────────────────────────────────────────────────
def test_le_catalogue_nomme_chaque_outil(outils, indexe):
    """Un outil absent du menu est un outil que le modèle ne peut pas réclamer :
    il ne voit ni sa sélection ni son nom, donc il conclut que la capacité
    n'existe pas et explique comment faire à la main."""
    menu = catalogue.menu()

    manquants = [o.name for o in outils if f"\n{o.name}:" not in f"\n{menu}"]

    assert manquants == []


def test_chaque_ligne_du_catalogue_porte_un_resume(indexe):
    """Un nom sans description ne se choisit pas mieux qu'un nom absent."""
    lignes = [l for l in catalogue.menu().splitlines() if l.strip()]

    nus = [l for l in lignes if len(l.split(":", 1)[-1].strip()) < 5]

    assert nus == []


def test_obtenir_outil_ne_se_reclame_pas_lui_meme(indexe):
    """Le seul outil que le menu doit taire : il est déjà lié à chaque tour."""
    assert "\nobtenir_outil:" not in f"\n{catalogue.menu()}"


def test_un_outil_exclu_disparait_du_menu(outils, indexe):
    """Le mode plan et la délégation retirent des outils : le menu doit suivre,
    sinon le modèle réclame un nom qu'on lui refusera."""
    cible = outils[0].name

    assert f"\n{cible}:" not in f"\n{catalogue.menu(frozenset({cible}))}"


# ── ce que le catalogue sait rendre ───────────────────────────────────────────
def test_un_nom_du_menu_se_resout_en_outil(outils, indexe):
    """Le contrat du filet : ce que le menu nomme, `outil()` le rend."""
    for ligne in catalogue.menu().splitlines()[:20]:
        nom = ligne.split(":", 1)[0]
        assert catalogue.connu(nom), nom
        assert catalogue.outil(nom) is not None, nom


def test_un_nom_inconnu_ne_leve_pas(indexe):
    """Le modèle invente parfois un nom. Ça ne doit pas faire tomber le tour."""
    assert catalogue.outil("outil_qui_nexiste_pas") is None
    assert not catalogue.connu("outil_qui_nexiste_pas")


# ── le plafond d'ouvertures ───────────────────────────────────────────────────
def test_le_plafond_douvertures_laisse_de_la_marge():
    """Le plafond borne un modèle en difficulté qui ouvrirait outil sur outil.
    Trop bas, il coupe le seul mécanisme qui rattrape le routage.

    Les six échecs mesurés sur le corpus réel ne demandent qu'UNE ouverture
    chacun ; le plafond n'est donc pas ce qui limite aujourd'hui. Ce test le fige
    pour que le constat reste vrai."""
    assert catalogue.OUVERTURES_MAX >= 3


# ── le prompt dit que la liste est partielle ──────────────────────────────────
def test_le_prompt_annonce_une_selection_incomplete(outils):
    """Sans cette phrase, le modèle prend sa sélection pour l'ensemble de ses
    capacités — c'est le comportement observé avant l'ajout du catalogue."""
    from src.llm.prompts.orchestrateur import build_system_prompt

    prompt = build_system_prompt(
        [o.name for o in outils[:5]], "2026-01-01", "kaine",
        catalogue=catalogue.menu() if catalogue._par_nom else "get_weather_by_city: météo",
    )

    assert "INCOMPLETE" in prompt.upper()
    assert "obtenir_outil" in prompt


def test_sans_catalogue_le_prompt_ne_promet_rien(outils):
    """Le catalogue est vide au tour de synthèse forcée : le prompt ne doit pas
    inviter à réclamer un outil dans un tour où plus rien n'est lié."""
    from src.llm.prompts.orchestrateur import build_system_prompt

    prompt = build_system_prompt([o.name for o in outils[:5]], "2026-01-01", "kaine",
                                 catalogue="")

    assert "obtenir_outil" not in prompt


# ── l'ordre de repli des backends ─────────────────────────────────────────────
def test_le_local_vient_en_dernier():
    """`noms()` rend l'ordre de DÉCLARATION, où `ollama` est premier parce qu'il
    est le plus ancien. Tout ce qui prenait « le premier disponible » mesurait
    donc sur un modèle local, et un taux produit par un 4B ne dit rien de la
    production."""
    from src.llm.backends import ORDRE_DE_REPLI

    assert ORDRE_DE_REPLI[0] == "ollama_cloud"
    assert ORDRE_DE_REPLI[-1] == "ollama"


def test_la_chaine_finit_toujours_par_un_backend_utilisable():
    """`ollama` ne demande aucune clé : la chaîne ne peut pas être vide."""
    from src.llm.backends import ordre_de_repli

    assert "ollama" in ordre_de_repli()


def test_un_backend_hors_chaine_reste_joignable():
    """Ajouter un backend sans penser à l'inscrire dans la chaîne ne doit pas le
    rendre invisible."""
    from src.llm.backends import ordre_de_repli, utilisables

    assert set(ordre_de_repli()) == set(utilisables())
