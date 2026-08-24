"""Rassembler avant d'écrire — et pourquoi le prompt disait le contraire.

Symptôme : « fais-moi un rapport de vingt pages sur la Seconde Guerre mondiale,
fais-le sur Google Doc » produisait `google_docs_create` puis `google_docs_update`,
sans la moindre recherche — alors que le plan du modèle annonçait « Rechercher
des sources fiables » en étape 2.

Le routage n'y était pour rien : `web_research_report`, `web_search_news` et
`url_fetch` étaient tous les trois proposés. Le modèle obéissait au prompt, qui
lui disait littéralement de créer le document EN PREMIER :

    ━━ GOOGLE DOCS ━━
    Never invent a doc_id. Use google_docs_create or drive_find_file_id first.

Ce « first » ne parlait que de l'ordre `create` → `update`. Lu par le modèle, il
est devenu l'ordre des ÉTAPES DE LA TÂCHE.

Mesuré sur `mistral-small-2603`, quatre tirages par variante, sur la requête
exacte de l'utilisateur — ce que le modèle demande au premier tour :

    variante                      cherche d'abord   crée le doc d'abord
    d'origine                          0/4                4/4
    `_GOOGLE` reformulé seul           1/4                3/4
    `_GOOGLE` + `_WEB` renforcés       4/4                0/4

Aucune des deux retouches ne suffit seule. Corriger `_GOOGLE` lève l'interdit
sans donner de raison de chercher ; renforcer `_WEB` donne la raison mais ne
lève pas l'interdit. C'est la conjonction qui déplace le comportement — et c'est
la mesure qui l'a montré, ma première conclusion ayant été que `_WEB` seul ne
servait à rien.

Ces tests portent sur le TEXTE du prompt, pas sur le modèle : faire dépendre la
suite d'un appel réseau et d'un tirage stochastique la rendrait intermittente.
"""
from datetime import date

import pytest

from src.llm.prompts import build_system_prompt

OUTILS_RAPPORT = [
    "web_research_report", "web_search_news", "url_fetch",
    "google_docs_create", "google_docs_write", "drive_find_file_id",
]


def _prompt(outils=OUTILS_RAPPORT) -> str:
    return build_system_prompt(outils, date.today().isoformat(), "Kaine", lang="fr")


def test_le_prompt_n_ordonne_plus_de_creer_le_document_en_premier():
    """La phrase exacte qui produisait le défaut ne doit pas revenir."""
    assert "drive_find_file_id first." not in _prompt()


def test_l_ordre_du_doc_id_reste_dit():
    """On ne jette pas la consigne d'origine : sans elle, le modèle invente un
    `doc_id` et l'écriture échoue. On la restreint à ce qu'elle voulait dire."""
    p = _prompt()

    assert "Never invent a doc_id" in p
    assert "doc_id ONLY" in p


def test_le_prompt_dit_de_rassembler_avant_de_creer():
    p = _prompt()

    assert "Never create a document before you have its content" in p


def test_le_prompt_dit_de_chercher_avant_de_rediger_un_rapport():
    """L'autre moitié du correctif : lever l'interdit ne suffit pas, il faut une
    raison positive de chercher — mesuré 1/4 contre 4/4."""
    p = _prompt()

    assert "REPORT" in p
    assert "gather sources FIRST" in p


def test_les_deux_moities_sont_presentes_ensemble():
    """Mesure : `_GOOGLE` seul donne 1/4, `_WEB` seul 0/4, les deux 4/4. Un test
    qui ne vérifierait qu'une moitié laisserait passer une régression à 1/4."""
    p = _prompt()

    assert "gather sources FIRST" in p and "Never create a document" in p


# ── Le contrepoids ────────────────────────────────────────────────────────────
def test_la_consigne_de_recherche_n_apparait_pas_sans_outil_de_recherche():
    """Sans outil de recherche, exiger de chercher rendrait le prompt menteur —
    et le modèle tenterait un appel qui n'existe pas."""
    p = build_system_prompt(["google_docs_create", "google_docs_write"],
                            date.today().isoformat(), "Kaine", lang="fr")

    assert "gather sources FIRST" not in p


def test_la_consigne_google_n_apparait_pas_sans_outil_google():
    p = build_system_prompt(["web_research_report"], date.today().isoformat(),
                            "Kaine", lang="fr")

    assert "Never invent a doc_id" not in p


def test_repondre_de_connaissance_reste_permis():
    """Le contrepoids mesuré : « explique la récursion », « traduis », « 17*24 »
    ne doivent DÉCLENCHER aucune recherche. La règle générale reste donc en
    place — on ajoute une exception pour les livrables, on ne l'inverse pas."""
    assert "answer from knowledge, no tool needed" in _prompt()


@pytest.mark.parametrize("section", ["━━ SEARCH ━━", "━━ GOOGLE DOCS ━━"])
def test_les_sections_restent_conditionnelles(section):
    """Le prompt n'inclut que ce qui sert : c'est ce qui le garde court."""
    nu = build_system_prompt(["get_current_time"], date.today().isoformat(),
                             "Kaine", lang="fr")

    assert section not in nu
