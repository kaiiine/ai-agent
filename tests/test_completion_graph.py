"""`--update` n'était annoncé nulle part.

`/graph <projet> --update` réextrait le code SANS appel de modèle, et c'est la
bonne réponse dans la quasi-totalité des cas — mais il fallait connaître le
drapeau pour s'en servir. Sans lui, on relance une extraction complète, ou bien
on ne relance rien et le graphe vieillit en silence : celui de ce dépôt annonçait
`revision.py L78` pour une fonction passée ligne 162.

La complétion dit aussi QUEL projet a déjà un graphe, et de quand il date : on
voit lequel a besoin d'être rafraîchi sans avoir à chercher.
"""
from __future__ import annotations

import pytest
from prompt_toolkit.document import Document

from src.ui import completer as comp
from src.ui.commands import _recoller_la_question
from src.ui.completer import SlashCompleter


@pytest.fixture(autouse=True)
def _cache_neuf():
    comp._graph_cache = []
    comp._graph_cache_ts = 0.0
    yield
    comp._graph_cache = []
    comp._graph_cache_ts = 0.0


@pytest.fixture
def projets(tmp_path, monkeypatch):
    """Deux projets, dont un seul a un graphe."""
    (tmp_path / "avec-graphe" / "graphify-out").mkdir(parents=True)
    (tmp_path / "avec-graphe" / "graphify-out" / "graph.json").write_text("{}")
    (tmp_path / "sans-graphe").mkdir()
    (tmp_path / ".cache").mkdir()
    monkeypatch.setattr("src.utils.paths.get_projects_dir", lambda: tmp_path)
    return tmp_path


def propositions(texte: str) -> list[tuple[str, str]]:
    doc = Document(texte, len(texte))
    return [(p.text, p.display_meta_text or "")
            for p in SlashCompleter().get_completions(doc, None)]


def test_la_commande_sinsere_nue(projets):
    """Le texte de la liste est INSÉRÉ, pas seulement affiché : `/graph [projet]`
    collerait un gabarit à éditer à la main."""
    assert propositions("/gra")[0][0] == "/graph"


def test_les_projets_sont_proposes(projets):
    noms = [n for n, _ in propositions("/graph ")]

    assert "avec-graphe" in noms
    assert "sans-graphe" in noms


def test_celui_qui_a_un_graphe_vient_en_premier(projets):
    noms = [n for n, _ in propositions("/graph ")]

    assert noms.index("avec-graphe") < noms.index("sans-graphe")


def test_la_date_du_graphe_est_annoncee(projets):
    meta = dict(propositions("/graph "))

    assert "graphe du" in meta["avec-graphe"]
    assert "aucun graphe" in meta["sans-graphe"]


def test_les_dossiers_caches_sont_ignores(projets):
    assert ".cache" not in [n for n, _ in propositions("/graph ")]


def test_le_prefixe_filtre(projets):
    assert [n for n, _ in propositions("/graph avec")] == ["avec-graphe"]


def test_ce_quon_peut_faire_du_projet_est_propose(projets):
    noms = [n for n, _ in propositions("/graph avec-graphe ")]

    assert "--update" in noms
    assert {"explain", "path", "affected"} <= set(noms)


def test_update_est_propose_sans_projet(projets):
    """`/graph --update` est valide : sans projet, il travaille sur le cwd."""
    assert "--update" in [n for n, _ in propositions("/graph --")]


def test_update_nest_pas_propose_deux_fois(projets):
    assert propositions("/graph avec-graphe --update ") == []


def test_une_racine_illisible_ne_casse_pas_la_saisie(monkeypatch):
    """La complétion tourne à chaque frappe : elle ne doit jamais lever.

    `--update` reste proposé — il ne dépend pas de la racine des projets."""
    def _explose():
        raise OSError("racine illisible")

    monkeypatch.setattr("src.utils.paths.get_projects_dir", _explose)
    noms = [n for n, _ in propositions("/graph ")]

    assert "explain" in noms, "les sous-commandes ne dépendent pas de la racine"
    assert "--update" in noms
    assert "avec-graphe" not in noms


# ── les commandes qui INTERROGENT le graphe ───────────────────────────────────
# `/graph <projet>` construit ; `query`, `explain`, `path`, `affected` lisent.
# L'agent de code les a déjà comme outils — les exposer ici les met sous la main
# de l'utilisateur, à zéro token : ce sont des sous-processus, pas des appels.
def test_une_sous_commande_est_proposee_sans_projet(projets):
    """Sans projet, `/graph` travaille sur le cwd — la forme est valide."""
    assert "explain" in [n for n, _ in propositions("/graph expl")]


def test_query_nest_plus_suggeree(projets):
    """Mesuré sur ce dépôt (13 922 nœuds) : `query` part de nœuds trouvés par
    ressemblance de NOM — « Comment » attrape « Comment une issue se règle, du
    point de vue du parieur » — et la traversée à profondeur 2 y atteint tout
    depuis n'importe où, jusqu'à 649 nœuds pour un symbole pourtant exact.
    Suggérer ce qui déçoit n'aide personne."""
    assert "query" not in [n for n, _ in propositions("/graph avec-graphe ")]
    assert "query" not in [n for n, _ in propositions("/graph que")]


def test_query_reste_utilisable_si_on_la_tape():
    """Ne plus la suggérer n'est pas la retirer : l'analyseur doit continuer de
    la reconnaître, sinon `query` serait pris pour un nom de dossier."""
    from src.ui.commands import GRAPH_SOUS_COMMANDES

    assert "query" in GRAPH_SOUS_COMMANDES
    assert _recoller_la_question(["query", "la", "revue"])[:2] == ["query", "la revue"]


def test_apres_la_sous_commande_on_ne_devine_plus(projets):
    """Les arguments sont libres : un symbole, une question."""
    assert propositions("/graph avec-graphe explain ") == []


def test_la_liste_nest_pas_recopiee():
    """Une copie dérive — celle des backends avait perdu `mistral`, puis
    `nvidia` : deux backends utilisables et invisibles à qui découvre par Tab."""
    from src.ui.commands import GRAPH_SOUS_COMMANDES
    from src.ui.completer import _graph_sous_commandes

    assert set(_graph_sous_commandes()) <= set(GRAPH_SOUS_COMMANDES)
    assert all(_graph_sous_commandes()[n] == GRAPH_SOUS_COMMANDES[n]
               for n in _graph_sous_commandes())


def test_toutes_les_sous_commandes_sont_reconnues_par_la_commande():
    """La complétion ne doit rien proposer que l'analyseur prendrait pour un
    nom de dossier."""
    import shlex

    from src.ui.commands import GRAPH_SOUS_COMMANDES

    for nom in GRAPH_SOUS_COMMANDES:
        mots = shlex.split(f"ai-agent {nom} x")
        coupe = next((i for i, m in enumerate(mots) if m in GRAPH_SOUS_COMMANDES),
                     len(mots))
        assert mots[:coupe] == ["ai-agent"], nom
        assert mots[coupe] == nom


# ── le découpage de la ligne ──────────────────────────────────────────────────
# `shlex` prend l'apostrophe française pour un guillemet ouvrant : « /graph
# ai-agent query Comment fonctionne l'agent code » était refusé pour « guillemet
# non fermé ». Une question en français en contient presque toujours une.
import pytest as _pytest

from src.ui.commands import _recoller_la_question


@_pytest.mark.parametrize("mots, attendu", [
    (["query", "Comment", "fonctionne", "l'agent", "code"],
     ["query", "Comment fonctionne l'agent code", "--budget", "700"]),
    (["query", '"Comment', 'fonctionne"'],
     ["query", "Comment fonctionne", "--budget", "700"]),
    (["query", "la", "revue", "--budget", "500"],
     ["query", "la revue", "--budget", "500"]),
    (["query", "la", "revue"], ["query", "la revue", "--budget", "700"]),
    (["explain", "reviser"], ["explain", "reviser"]),
    (["explain", '"reviser"'], ["explain", "reviser"]),
    (["path", "coder", "reviser"], ["path", "coder", "reviser"]),
    (["affected", "reviser", "--depth", "3"], ["affected", "reviser", "--depth", "3"]),
    (["god-nodes", "--top", "5"], ["god-nodes", "--top", "5"]),
    (["query"], ["query"]),
    ([], []),
])
def test_la_ligne_se_decoupe_sans_shlex(mots, attendu):
    assert _recoller_la_question(mots) == attendu


def test_une_apostrophe_ne_casse_plus_la_commande():
    """Le cas vécu, mot pour mot."""
    recolle = _recoller_la_question(
        "query Comment fonctionne l'agent code".split())

    assert recolle[:2] == ["query", "Comment fonctionne l'agent code"]


def test_les_drapeaux_ne_sont_pas_avales_par_la_question():
    """Sans ça, `--budget 500` partait dans le texte de la question."""
    recolle = _recoller_la_question(["query", "la", "revue", "--budget", "500"])

    assert recolle[1] == "la revue"
    assert recolle[2:] == ["--budget", "500"]


def test_la_traversee_est_servie_en_portion_lisible():
    """Le plafond de graphify est de 2000 tokens : à l'écran, une soixantaine de
    nœuds bruts défilent, et sur un dépôt hétérogène la plupart n'ont rien à
    voir — la traversée à profondeur 2 y atteint tout depuis n'importe où
    (mesuré : 385 nœuds depuis `run_coding_agent`)."""
    from src.ui.commands import _BUDGET_QUERY

    recolle = _recoller_la_question(["query", "agent", "code"])

    assert recolle[-2:] == ["--budget", str(_BUDGET_QUERY)]
    assert _BUDGET_QUERY < 2000


def test_un_budget_choisi_nest_pas_ecrase():
    recolle = _recoller_la_question(["query", "agent", "--budget", "5000"])

    assert recolle.count("--budget") == 1
    assert recolle[-1] == "5000"


def test_les_commandes_precises_nont_pas_de_budget_impose():
    """`explain` et `path` partent d'un point précis : rien à plafonner."""
    for mots in (["explain", "reviser"], ["path", "coder", "reviser"]):
        assert "--budget" not in _recoller_la_question(mots)


# ── quel backend fait l'extraction ────────────────────────────────────────────
# graphify a son ordre — `gemini → kimi → claude → openai → deepseek`, ollama en
# dernier — raisonnable pour un usage général : une clé payante ne doit pas être
# masquée par un `OLLAMA_BASE_URL` de passage. Mais le choix appartient à
# l'utilisateur, et il se lit ici plutôt que de dépendre de l'ordre d'un tiers.
def test_gemini_est_le_defaut(monkeypatch):
    from src.ui import commands as c

    monkeypatch.delenv("AXON_GRAPHIFY_BACKEND", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    assert c._backend_extraction() == ["--backend", "gemini"]


def test_google_api_key_convient_aussi(monkeypatch):
    from src.ui import commands as c

    monkeypatch.delenv("AXON_GRAPHIFY_BACKEND", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "x")

    assert c._backend_extraction() == ["--backend", "gemini"]


def test_la_variable_denvironnement_a_le_dernier_mot(monkeypatch):
    """Pour basculer sur ollama, deepseek ou autre sans toucher au code."""
    from src.ui import commands as c

    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("AXON_GRAPHIFY_BACKEND", "ollama")

    assert c._backend_extraction() == ["--backend", "ollama"]


def test_sans_cle_on_laisse_graphify_decider(monkeypatch):
    """Nommer un backend sans clé ferait échouer l'extraction en promettant le
    contraire — la même erreur que `OLLAMA_MODEL=qwen2.5-coder:7b`, déclaré dans
    `.env` et jamais tiré sur cette machine."""
    from src.ui import commands as c

    for var in ("AXON_GRAPHIFY_BACKEND", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    assert c._backend_extraction() == []
