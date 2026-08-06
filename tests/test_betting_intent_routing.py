"""Toute intention de pari atteint `betting_recommend`, quel que soit l'embedding.

Le routing d'outils est un plus-proche-voisin sur un corpus d'embeddings. Son
résultat dérive : le corpus change, le modèle d'embedding est re-téléchargé, et
un groupe qui sortait 3e sort 7e. C'est acceptable pour choisir entre
`local_grep` et `local_glob`. Ça ne l'est pas pour décider si l'outil qui engage
de l'argent est présent dans la sélection.

Mesuré avant la porte déterministe : deux intentions sur douze n'élisaient jamais
le groupe `quant` — « que dois-je jouer ce soir » et « scanne tout ce qui est
disponible aujourd'hui et demain », c'est-à-dire les formulations mêmes du dump.
Sans `betting_recommend` dans la sélection, le modèle ne dispose plus que
d'outils de données, et refait exactement ce que la fermeture vient d'interdire.

Ces tests portent sur la PORTE, pas sur le vectoriel : ils doivent rester verts
même si l'index est reconstruit avec un autre modèle d'embedding.
"""

from __future__ import annotations

import pytest

from src.orchestrator.tool_retriever import _money_intent

#: Les intentions à protéger. Chacune doit rendre `betting_recommend` disponible.
INTENTIONS = [
    # lexique explicite
    "recommande-moi un pari",
    "quels sont les meilleurs paris",
    "un pari simple ou combiné",
    "trouve moi une bonne occasion de parier",
    "des paris maintenant",
    "je veux doubler ma mise ce soir",
    "quelle cote sur le match de ce soir",
    "j'ai 20 euros de bankroll et 20 euros de freebets",
    "un pronostic pour demain",
    # aucun mot du lexique du pari
    "que dois-je jouer ce soir",
    "je joue quoi ce soir",
    "quoi jouer demain matin",
    # formulation exacte du dump
    "scanne tout ce qui est disponible aujourd'hui et demain",
    "scanne les matchs dispo ce soir",
]

#: Requêtes qui ne doivent PAS déclencher la porte. Un faux positif ne coûte
#: qu'un outil de plus dans le prompt — mais une porte qui s'ouvre sur tout
#: n'est plus une porte, et le prompt betting s'injecterait partout.
HORS_SUJET = [
    "lis le fichier src/main.py",
    "montre moi le dernier commit",
    "envoie un mail a paul",
    "scanne le dossier src pour trouver les TODO",
    "quelle est la meteo demain",
    "resume moi mes mails de ce matin",
    "lance les tests",
    "quelle musique jouer pendant le trajet",
]


@pytest.mark.parametrize("requete", INTENTIONS)
def test_chaque_intention_de_pari_ouvre_la_porte(requete):
    assert _money_intent(requete), f"intention de pari non détectée : {requete!r}"


@pytest.mark.parametrize("requete", HORS_SUJET)
def test_aucune_requete_hors_sujet_n_ouvre_la_porte(requete):
    assert not _money_intent(requete), f"faux positif : {requete!r}"


def test_la_porte_ne_retire_jamais_un_groupe():
    """Elle ADJOINT `quant`, elle ne substitue rien. Le rang 1 reste celui du
    sémantique — sans quoi le dépouillement `coding` changerait de déclencheur et
    « lis le fichier src/main.py » reperdrait son outil de lecture."""
    import inspect

    from src.orchestrator import tool_retriever

    source = inspect.getsource(tool_retriever.ToolRetriever.get)

    assert "groups.append(_MONEY_GROUP)" in source
    assert "ranked[0] == \"coding\"" in source


def test_la_porte_precede_le_semantique_et_ne_depend_pas_de_lui():
    """Le test qui donne sa valeur aux autres : `_money_intent` ne touche ni au
    store, ni à l'embedder. Sa réponse est la même sur une machine sans Ollama."""
    import inspect

    from src.orchestrator import tool_retriever

    source = inspect.getsource(tool_retriever._money_intent)

    for dependance in ("self", "_store", "similarity", "embed"):
        assert dependance not in source


# ── Bout en bout : la sélection réelle contient bien l'outil ──────────────────
@pytest.fixture(scope="module")
def retriever():
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import ToolRetriever

    return ToolRetriever(build_all_tools())


@pytest.mark.parametrize("requete", INTENTIONS)
def test_la_selection_reelle_contient_betting_recommend(retriever, requete):
    """La porte est une condition nécessaire ; ce test vérifie qu'elle suffit —
    que le groupe élu livre bien l'outil jusqu'au bout de l'étage 2."""
    noms = {t.name for t in retriever.get(requete)}

    assert "betting_recommend" in noms, f"outil absent de la sélection : {requete!r}"
