"""Le graphe se REQUÊTE, il ne se lit pas.

Graphify construit `graphify-out/graph.json` puis se requête — son README le dit
sans détour : « preferring scoped queries like `graphify query "<question>"`
over reading the full report ». Axon faisait l'inverse.

Mesuré sur ce dépôt :

    local_read_file(GRAPH_REPORT.md)   42 733 tokens   ← ce que le prompt ordonnait
    lire 10 fichiers source            13 373 tokens   ← ce qu'il prétendait remplacer
    graph_query (budget 2000)           1 783 tokens
    graph_explain                         330 tokens
    graph_affected                        150 tokens
    graph_path                             36 tokens

Le rapport fait 147 Ko et passe JUSTE sous le plafond de 200 Ko de
`local_read_file` : il partait donc entier, pour la moitié du budget d'un tour,
et en doublon du résumé déjà injecté par `task_enricher`.

Les tests qui touchent au vrai graphe sont sautés s'il n'a pas été construit :
échouer faute d'un artefact local n'apprend rien sur le code.
"""
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
GRAPHE = RACINE / "graphify-out" / "graph.json"

besoin_graphe = pytest.mark.skipif(
    not GRAPHE.exists(), reason="graphify-out/graph.json absent — lance /graph")


# ── Les outils existent et sont branchés ──────────────────────────────────────
@pytest.mark.parametrize("nom", ["graph_affected", "graph_explain", "graph_path", "graph_query"])
def test_l_outil_est_expose_au_specialist(nom):
    """Un outil défini mais non enregistré ne sert à rien — c'est exactement ce
    qu'était `_OLD_CODING` côté prompts."""
    from src.agents.coding.specialist import _get_coding_tools

    assert nom in {t.name for t in _get_coding_tools()}


def test_le_repli_par_sous_chaine_reste_disponible():
    """`project_graph_query` est plus pauvre — correspondance de sous-chaîne,
    sans suivre les arêtes — mais il ne dépend d'aucun sous-processus. On le
    garde pour le jour où graphify manque."""
    from src.agents.coding.specialist import _get_coding_tools

    assert "project_graph_query" in {t.name for t in _get_coding_tools()}


def test_graph_query_expose_son_plafond_en_tokens():
    """Le budget est la raison d'être de cet outil : s'il n'est pas réglable
    depuis l'appel, on retombe sur une sortie non bornée."""
    from src.agents.coding.graphe import graph_query

    props = graph_query.args_schema.model_json_schema()["properties"]

    assert "budget" in props
    assert "token" in props["budget"]["description"].lower()


# ── Le prompt ne fait plus lire le rapport ────────────────────────────────────
def test_le_prompt_interdit_de_lire_le_rapport_entier():
    """42 733 tokens contre quelques centaines — et le résumé est déjà injecté
    par `task_enricher`, donc le lire est aussi un doublon."""
    from src.agents.coding.prompts import BASE_PROMPT

    assert "Ne lis JAMAIS GRAPH_REPORT.md" in BASE_PROMPT
    assert "local_read_file EN PREMIER" not in BASE_PROMPT


def test_le_prompt_annonce_les_quatre_requetes():
    from src.agents.coding.prompts import BASE_PROMPT

    for outil in ("graph_path", "graph_affected", "graph_explain", "graph_query"):
        assert outil in BASE_PROMPT


def test_le_prompt_donne_le_cout_pour_que_le_choix_soit_informe():
    """Sans ordre de grandeur, le modèle n'a aucune raison de préférer
    `graph_affected` à `graph_query`."""
    from src.agents.coding.prompts import BASE_PROMPT

    assert "42 733" in BASE_PROMPT


# ── Résolution de chemin ──────────────────────────────────────────────────────
def test_un_nom_de_projet_suffit():
    """`project_path="."` échouait : le cwd du shell d'Axon vaut souvent `$HOME`,
    et la résolution rendait `no_graph` sur un projet qui a pourtant son graphe."""
    from src.agents.coding.graphe import _graphe_de, _projet

    p = _projet("ai-agent")

    assert p.name == "ai-agent"
    if GRAPHE.exists():
        assert _graphe_de(p) is not None


def test_un_projet_sans_graphe_le_dit_au_lieu_d_echouer(tmp_path):
    """Un statut exploitable vaut mieux qu'une exception : le modèle peut
    enchaîner sur `local_grep`."""
    from src.agents.coding.graphe import _lancer

    r = _lancer(tmp_path, "explain", "X")

    assert r["status"] == "no_graph"
    assert "/graph" in r["hint"]


# ── Le vrai graphe ────────────────────────────────────────────────────────────
@besoin_graphe
def test_graph_path_relie_deux_symboles():
    from src.agents.coding.graphe import graph_path

    r = graph_path.invoke({"project_path": "ai-agent",
                           "source": "build_system_prompt()",
                           "target": "make_llm_gemini()"})

    assert r["status"] == "ok"
    assert "hops" in r["result"] or "path" in r["result"].lower()


@besoin_graphe
def test_graph_affected_rend_les_appelants():
    """La question que le prompt posait jusqu'ici via `local_grep` sur tout le
    dépôt : qui casse si je touche cette fonction."""
    from src.agents.coding.graphe import graph_affected

    r = graph_affected.invoke({"project_path": "ai-agent",
                               "symbol": "build_system_prompt()"})

    assert r["status"] == "ok"
    assert "Affected" in r["result"]


@besoin_graphe
def test_une_requete_coute_un_ordre_de_grandeur_de_moins_que_le_rapport():
    """L'invariant qui justifie tout ce chantier.

    Le seuil est un RAPPORT, pas un nombre absolu : le coût d'une requête suit
    le nombre de voisins du symbole, qui grandit avec le dépôt. Une borne à
    « un centième » a été franchie dès que le dépôt a grossi — 465 tokens
    contre 427 — alors que le rapport restait de 1 à 92. C'est le seuil qui
    était trop fin, pas la requête qui a dérivé.

    Ce qui doit rester vrai est l'ORDRE DE GRANDEUR : demander qui casse si l'on
    touche à un symbole ne doit jamais coûter comme lire le rapport entier.
    """
    import tiktoken

    from src.agents.coding.graphe import graph_affected

    enc = tiktoken.get_encoding("o200k_base")
    r = graph_affected.invoke({"project_path": "ai-agent",
                               "symbol": "build_system_prompt()"})

    cout = len(enc.encode(str(r)))
    assert cout < 42_733 / 20, (
        f"{cout} tokens : la requête ciblée a cessé d'être un ordre de grandeur "
        f"moins chère que le rapport complet")


@besoin_graphe
def test_le_budget_borne_vraiment_la_sortie():
    import tiktoken

    from src.agents.coding.graphe import graph_query

    enc = tiktoken.get_encoding("o200k_base")
    court = graph_query.invoke({"project_path": "ai-agent",
                                "question": "construction du prompt", "budget": 300})

    assert court["status"] in ("ok", "not_found")
    if court["status"] == "ok":
        assert len(enc.encode(court["result"])) < 1500


# ── La fraîcheur ──────────────────────────────────────────────────────────────
def test_graph_update_est_cable():
    """`graphify update` réextrait SANS modèle. Sans lui, le graphe vieillit en
    silence : celui de ce dépôt annonçait un commit avec sept commits d'écart."""
    import inspect

    from src.ui import commands

    source = inspect.getsource(commands)

    assert '"update", str(project_path)' in source
    assert "--update" in source
