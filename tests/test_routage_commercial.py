"""Une requête commerciale ne doit pas partir vers un fil d'actualités.

Vécu : « trouve des codes promo pour le Lenovo Legion 7i et teste-les » routait
vers `web_search_news`, qui interroge DuckDuckGo **News**. Un code promo n'y
figure jamais — il vit sur des pages d'agrégateurs. La réponse rendue, « aucun
code promo n'apparaît dans les actualités récentes », était littéralement vraie
et entièrement fausse : le mauvais instrument, pas le mauvais sujet.

La cause n'était pas un mauvais classement mais un VIDE : aucun groupe ne
couvrait le commerce, tandis que `news` revendiquait « annonces d'entreprises et
sorties de produits ». Faute de meilleur candidat, une question de prix y
atterrissait.

CE QUI A ÉTÉ ESSAYÉ, ET POURQUOI CE N'EST PAS CE QUI EST LÀ
-----------------------------------------------------------
Un groupe `commerce` dédié donnait le meilleur score de loin — 8/8 en réglage
ET 8/8 en held-out. Il est refusé pour deux raisons mesurées :

  1. Il devait déclarer `web_research_report`, déjà dans `search`. Or un outil
     ne peut appartenir qu'à UN groupe : l'index inverse en écrase un
     silencieusement (cf. test_key_pool_fallback.py). `extend` n'aide pas — il
     étend le document, pas la liste d'outils.
  2. Un groupe de plus concurrence TOUS les autres à l'étage 1. Mesuré :
     « quels sont mes rendez vous de demain » perdait `calendar`, et
     « souviens-toi de cette préférence » perdait `memory`.

Reste donc le correctif conservateur : retirer à `news` la formule qui attirait
les questions de produit, et donner à `search` les mots-clés commerciaux. Il ne
rattrape pas tout — c'est un PLANCHER mesuré, pas une cible.
"""
from __future__ import annotations

import pytest

from src.orchestrator.registry import build_all_tools
from src.orchestrator.tool_retriever import TOOL_GROUPS, ToolRetriever

#: Rattrapées par le correctif. Chacune échouait avant.
CORRIGEES = [
    "trouve des codes promo pour le Lenovo Legion 7i Gen 7",
    "y a-t-il un code de réduction pour cet article",
    "quel est le prix du Lenovo Legion 7i",
    "compare les prix de la RTX 4080 chez plusieurs marchands",
    "trouve le meilleur prix pour un iPhone 15",
    "est-ce que ce pc portable est en promo en ce moment",
    "à quel tarif se vend le Steam Deck",
    "existe-t-il un bon de réduction pour Decathlon",
    "quelles sont les ristournes en cours chez Dell",
    "y a-t-il des remises pour les étudiants chez Apple",
]

#: Held-out : vocabulaire jamais utilisé pour choisir un mot-clé. Sert de plancher.
HELD_OUT = [
    "est-ce que la Nintendo Switch 2 est moins chère quelque part",
    "je cherche une offre sur un casque Bose",
    "à quel tarif se vend le Steam Deck",
    "existe-t-il un bon de réduction pour Decathlon",
    "où trouver le moins cher ce disque dur",
    "quelles sont les ristournes en cours chez Dell",
    "y a-t-il des remises pour les étudiants chez Apple",
    "combien ça vaut un vélo électrique d'occasion",
]
#: Mesuré au moment du correctif : 4/8, contre 3/8 avant. Les échecs restants
#: sont des tournures sans aucun mot-clé — « moins chère », « une offre »,
#: « combien ça vaut ». Les rattraper demanderait de la SÉMANTIQUE, donc le
#: groupe dédié que l'architecture interdit. Ce chiffre est un plancher : s'il
#: monte, tant mieux ; s'il descend, quelque chose a régressé.
PLANCHER_HELD_OUT = 4

ACTUALITE = [
    "résultats du match PSG hier",
    "news Apple aujourd'hui",
    "qu'est-ce qui s'est passé en France cette semaine",
    "dernières annonces de Nvidia",
    "score du match de hier soir",
    "qui a gagné hier soir",
    "quoi de neuf sur la guerre en Ukraine",
    "communiqué de Tesla ce matin",
]

RECHERCHE = [
    "cherche la documentation de langchain",
    "trouve des papers arxiv sur les transformers",
    "récupère le contenu de cette URL",
]


@pytest.fixture(scope="module")
def retriever():
    return ToolRetriever(build_all_tools())


def _outils(retriever, requete: str) -> set[str]:
    return {t.name for t in retriever.get(requete)}


def test_aucun_outil_n_appartient_a_deux_groupes():
    """L'invariant qui a fait renoncer au groupe dédié. Nommé ici pour que la
    raison reste lisible depuis le correctif qu'elle a écarté."""
    declares = [n for spec in TOOL_GROUPS.values() for n in spec.tools]
    assert len(declares) == len(set(declares))


def test_news_ne_revendique_plus_les_sorties_de_produits():
    """La formule qui aspirait les questions de prix. `communiqués et annonces
    d'entreprises` reste : une annonce Nvidia EST une actualité."""
    assert "sorties de produits" not in TOOL_GROUPS["news"].covers
    assert "annonces d'entreprises" in TOOL_GROUPS["news"].covers


@pytest.mark.parametrize("requete", CORRIGEES)
def test_une_requete_commerciale_atteint_la_recherche_web(retriever, requete):
    assert "web_research_report" in _outils(retriever, requete), (
        f"« {requete} » n'atteint pas la recherche web")


@pytest.mark.parametrize("requete", CORRIGEES)
def test_une_requete_commerciale_ne_part_pas_vers_l_actualite(retriever, requete):
    """Le défaut d'origine, énoncé directement : c'est le fil d'actualités qui
    rendait « aucun code promo trouvé »."""
    outils = _outils(retriever, requete)
    assert not (outils == {"web_search_news"} or
                ("web_search_news" in outils and "web_research_report" not in outils)), (
        f"« {requete} » n'a que le fil d'actualités pour répondre")


def test_le_correctif_tient_hors_du_vocabulaire_de_reglage(retriever):
    """Plancher, pas cible : une correction qui ne vaut que sur ses propres
    exemples est un dictionnaire déguisé en intention."""
    reussies = sum("web_research_report" in _outils(retriever, q) for q in HELD_OUT)
    assert reussies >= PLANCHER_HELD_OUT, (
        f"held-out commercial à {reussies}/{len(HELD_OUT)}, "
        f"plancher {PLANCHER_HELD_OUT}")


@pytest.mark.parametrize("requete", ACTUALITE)
def test_l_actualite_reste_servie(retriever, requete):
    """Le correctif retire une formule à `news` : il doit prouver qu'il n'a rien
    emporté avec elle."""
    assert "web_search_news" in _outils(retriever, requete), (
        f"« {requete} » a perdu le fil d'actualités")


@pytest.mark.parametrize("requete", RECHERCHE)
def test_la_recherche_documentaire_est_intacte(retriever, requete):
    assert "web_research_report" in _outils(retriever, requete)
