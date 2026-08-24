"""Le routing doit tenir sur des PARAPHRASES, pas sur les phrases des tests.

Quatre cas échouaient : `git_status` sur « quels sont mes fichiers modifiés »,
`slack` sur « envoie le récap dans le salon », et `coding` qui s'invitait dans six
requêtes non-coding. Les corriger phrase par phrase aurait produit une liste de
correspondances exactes — verte, et fausse dès la première reformulation.

Ce fichier vérifie donc les VARIANTES, jamais les phrases corrigées. Il mesure
aussi ce qui ne doit PAS bouger : la porte déterministe betting, qui ne dépend
d'aucun embedding et doit rester insensible à ce réglage de corpus.
"""

from __future__ import annotations

import pytest

from src.orchestrator.registry import build_all_tools
from src.orchestrator.tool_retriever import TOOL_GROUPS, ToolRetriever


@pytest.fixture(scope="module")
def retriever(tmp_path_factory):
    """Index ISOLÉ : écrire dans ~/.axon/tool_store ferait dépendre le démarrage
    de l'utilisateur du dernier test lancé."""
    from src.orchestrator import tool_retriever as module

    store = tmp_path_factory.mktemp("tool_store") / "store"
    module._CACHE_DIR, module._CACHE_HASH = store, store / "fingerprint.txt"
    return ToolRetriever(build_all_tools())


# ── git : l'intention, pas le jargon ──────────────────────────────────────────
@pytest.mark.parametrize("requete,outil", [
    ("quels fichiers ai-je modifies ?", "git_status"),
    ("ou en est ma copie de travail", "git_status"),
    ("montre les changements du depot", "git_diff"),
])
def test_l_etat_du_depot_se_demande_sans_dire_git(retriever, requete, outil):
    """La description menait par « Dépôt git », l'index, le remisage — du jargon
    qui tirait l'embedding loin d'une question posée en français courant. « voir
    les fichiers modifiés » y figurait mot pour mot et le groupe ne sortait même
    pas dans les cinq premiers."""
    assert outil in {t.name for t in retriever.get(requete)}


# ── slack : salon, canal, channel ─────────────────────────────────────────────
@pytest.mark.parametrize("requete", [
    "envoie le recap dans le salon",
    "poste le compte rendu sur le salon general",
    "envoie ce resume dans le canal equipe",
    "previens l equipe sur slack",
    "balance ca dans le channel dev",
])
def test_les_trois_mots_du_salon_sont_discriminants(retriever, requete):
    """La description contenait déjà le mot « salon » et le groupe sortait hors du
    top 5 : l'embedder dilue un terme rare dans une phrase courte et banale. La
    correspondance exacte, elle, ne le rate jamais."""
    assert "slack_send_message" in {t.name for t in retriever.get(requete)}


# ── memory : intentions explicites seulement ──────────────────────────────────
@pytest.mark.parametrize("requete", [
    "souviens-toi de cette preference",
    "memorise que je prefere le francais",
    "note ca dans ta memoire projet",
])
def test_la_memoire_repond_aux_intentions_de_memoire(retriever, requete):
    assert "axon_note" in {t.name for t in retriever.get(requete)}


@pytest.mark.parametrize("requete", [
    "quels sont mes fichiers modifies en ce moment",
    "envoie le recap dans le salon",
    "montre moi le dernier commit",
    "lis le fichier src/main.py",
])
def test_la_memoire_n_absorbe_plus_les_requetes_generiques(retriever, requete):
    """Son document court et générique la logeait près du centroïde : elle
    sortait au rang 1 sur deux requêtes qui ne la concernaient en rien."""
    assert retriever._rank_groups(requete)[0] != "memory"


# ── coding : ni absent sur du vrai code, ni partout ailleurs ──────────────────
@pytest.mark.parametrize("requete", [
    "refactorise entierement mon projet react",
    "cree un site vitrine pour mon cabinet",
    "corrige le bug dans mon application next.js",
    "cree une landing page pour ma startup",
])
def test_une_vraie_demande_de_code_atteint_l_agent(retriever, requete):
    assert "run_coding_agent" in {t.name for t in retriever.get(requete)}


@pytest.mark.parametrize("requete", [
    "lis le fichier src/main.py",
    "telecharge le contenu de cette page web",
    "montre moi le dernier commit",
    "cherche sur internet les nouveautes de python 3.13",
])
def test_l_agent_de_code_ne_s_invite_pas_par_largeur_de_document(retriever, requete):
    """`run_coding_agent` DÉLÈGUE et écrit des fichiers. Le proposer parce qu'il
    est quatrième ou cinquième met à portée du modèle une action lourde que la
    requête ne demandait pas — ce qui n'est pas comparable à un `local_grep`
    admis au rang 5."""
    assert "run_coding_agent" not in {t.name for t in retriever.get(requete)}


def test_le_seuil_de_rang_est_declare_pas_code_en_dur(retriever):
    """Un seuil porté par le groupe se lit dans le registre et s'étend à un autre
    groupe le jour où un second outil deviendra aussi lourd. Un `if group ==
    "coding"` dans la sélection ne se verrait pas.

    Ce jour est arrivé : `quant` porte le même seuil depuis qu'on a mesuré
    « il me reste combien de stockage ? » embarquant ses sept outils au 4e rang,
    soit 45 % de l'entrée d'un tour. Le test vérifie donc le MÉCANISME — un seuil
    déclaré, jamais codé en dur — et non le nombre de groupes qui s'en servent.
    """
    assert TOOL_GROUPS["coding"].requires_top_rank == 3
    assert TOOL_GROUPS["quant"].requires_top_rank == 3

    import inspect

    from src.orchestrator import tool_retriever

    selection = inspect.getsource(tool_retriever.ToolRetriever.get)
    assert 'group == "coding"' not in selection
    assert 'group == "quant"' not in selection
    assert "requires_top_rank" in selection


# ── déterminisme ──────────────────────────────────────────────────────────────
def test_le_routing_est_reproductible(retriever):
    """Les quatre échecs corrigés étaient déterministes, pas du bruit : trois
    exécutions rendaient exactement le même classement. Un correctif mesuré sur
    un résultat instable ne voudrait rien dire."""
    requetes = ["quels sont mes fichiers modifies en ce moment",
                "envoie le recap dans le salon",
                "fais moi un schema de l'architecture"]
    attendu = {q: retriever._rank_groups(q) for q in requetes}
    for _ in range(3):
        assert {q: retriever._rank_groups(q) for q in requetes} == attendu


# ── non-régression betting : ce réglage ne doit rien y changer ────────────────
@pytest.mark.parametrize("requete", [
    "que dois-je jouer ce soir",
    "scanne tous les matchs aujourd'hui",
    "quels sont les meilleurs paris",
    "un pari simple ou combine",
    "j'ai 20 euros de bankroll",
    "il me reste un freebet",
    "tous les sports et toutes les competitions",
    "uniquement l'ATP aujourd'hui",
])
def test_le_reglage_du_corpus_ne_touche_pas_le_routing_betting(retriever, requete):
    """La porte d'intention money ne consulte ni le store ni l'embedder : elle
    doit donc être exactement insensible à un réglage de documents. C'est ce qui
    permet de retoucher le corpus sans rouvrir la fermeture de sûreté."""
    assert "betting_recommend" in {t.name for t in retriever.get(requete)}


@pytest.mark.parametrize("requete", [
    "lis le fichier src/main.py",
    "montre moi le dernier commit",
    "envoie le recap dans le salon",
    "souviens-toi de cette preference",
    "quelle musique jouer pendant le trajet",
])
def test_la_porte_money_ne_se_declenche_sur_aucune_requete_hors_sujet(requete):
    """C'est la PORTE qu'on vérifie, pas la sélection. Sur « quelle musique jouer
    pendant le trajet », `quant` remonte au rang 2 par pure similarité — un
    comportement du corpus, antérieur à cette wave et indépendant d'elle. Ce qui
    doit rester vrai, c'est que la porte déterministe, elle, ne s'ouvre pas."""
    from src.orchestrator.tool_retriever import _money_intent

    assert not _money_intent(requete)


@pytest.mark.parametrize("outil", [
    "ev_analyze", "parlay_analyze", "same_match_combo_analyze",
    "probability_compute", "winamax_odds_fetch",
])
def test_aucun_ancien_outil_quant_ne_remplace_betting_recommend(retriever, outil):
    """Ils restent disponibles en diagnostic — mais jamais SANS l'outil qui
    recommande, sinon le modèle retrouve la configuration exacte du dump."""
    selection = {t.name for t in retriever.get("quels sont les meilleurs paris")}
    if outil in selection:
        assert "betting_recommend" in selection
