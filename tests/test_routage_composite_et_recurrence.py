"""Les deux mécanismes ajoutés au routeur d'outils : découpage en clauses et
porte de récurrence.

Mesuré le 22/08/2026 sur les 298 sondes de `test_tool_routing.CORPUS`, en
regardant la SÉLECTION FINALE (`get`) et non le classement intermédiaire :

                        avant     après
    rappel global       85,2 %    89,3 %
    groupe `cron`       64,5 %   100,0 %
    sondes composites   69,6 %    73,9 %
    outils par requête    19,6      20,3

Le surcoût est concentré sur les requêtes composites (27,3 outils), qui
demandent réellement deux domaines. Les 275 sondes à une seule clause suivent le
chemin d'avant, à l'identique.
"""
from __future__ import annotations

import pytest

from src.orchestrator.tool_retriever import (
    TOOL_GROUPS, ToolRetriever, _clauses, _coding_intent, _money_intent,
    _recurrence_intent,
)


@pytest.fixture(scope="module")
def retriever():
    from src.orchestrator.registry import build_all_tools
    return ToolRetriever(build_all_tools())


# ── Découpage en clauses ──────────────────────────────────────────────────────
@pytest.mark.parametrize("requete, attendu", [
    ("lis le README et poste un résumé sur slack", 2),
    ("cherche la météo de demain et envoie-la moi par mail", 2),
    ("trouve les news sur l'OM, note-les dans ma mémoire", 2),
])
def test_une_requete_composite_est_decoupee(requete, attendu):
    assert len(_clauses(requete)) == attendu


@pytest.mark.parametrize("requete", [
    "quelle heure est-il ?",
    "lis le fichier src/main.py",
    "corrige le bug dans mon application next.js",
    "et toi ?",
])
def test_une_requete_simple_n_est_pas_decoupee(requete):
    """Retourner [] et non [requete] : c'est ce qui laisse le chemin d'avant
    intact — ni marge de distance, ni plafond d'union."""
    assert _clauses(requete) == []


def test_un_fragment_trop_court_n_est_pas_une_clause():
    """« et ça » n'est pas une intention, c'est du liant. L'embedder n'en tire
    rien et le router coûterait un groupe pour du bruit."""
    assert _clauses("fais-le et ça") == []


def test_le_decoupage_rattrape_ce_que_le_vecteur_unique_perd(retriever):
    """Le cas qui a motivé le mécanisme : « lis le README et poste un résumé sur
    slack » n'élit `filesystem` dans AUCUN des huit premiers groupes quand la
    requête est encodée d'un bloc — la moitié « slack » écrase la moitié
    « fichier ». Élargir la sélection ne le rattrape pas ; découper, si."""
    outils = {t.name for t in retriever.get("lis le README et poste un résumé sur slack")}
    assert outils & set(TOOL_GROUPS["filesystem"].tools), "la moitié « fichier » est perdue"
    assert outils & set(TOOL_GROUPS["slack"].tools), "la moitié « slack » est perdue"


def test_le_rang_vient_de_la_clause_et_non_de_l_union(retriever):
    """`requires_top_rank` dit « ce groupe doit être fortement impliqué ». L'être
    dans la seconde moitié de la phrase compte autant que dans la première : sans
    rang par clause, `coding` tomberait au rang 4 de l'union et son seuil de 3
    l'écarterait alors que sa clause l'élit en tête."""
    _, rangs = retriever._rank_groups_detaille("lis le README et corrige le bug du module")
    assert rangs.get("coding", 99) <= TOOL_GROUPS["coding"].requires_top_rank


def test_chaque_clause_est_servie_avant_qu_une_seule_se_resserve(retriever):
    """La fusion se fait À TOUR DE RÔLE, pas clause par clause.

    Vécu : « …le rag en détail, pas en dev en prod, ce qui change du dev et me
    schématiser tout ça ». La dernière clause élit `diagrams` au rang 2, mais
    les deux premières consommaient les 8 places de l'union et le groupe était
    coupé. L'utilisateur demandait un schéma et le modèle n'avait pas l'outil
    de schéma — il a répondu par du texte.

    Une clause est une intention : toutes doivent être représentées avant que
    l'une d'elles obtienne son deuxième choix.
    """
    requete = ("Tu peux regarder ce qu'est le rag en détail, pas en dev en prod, "
               "ce qui change du dev et me schématiser tout ça")
    assert len(_clauses(requete)) >= 4
    outils = {t.name for t in retriever.get(requete)}
    assert "mermaid_diagram" in outils, (
        "l'intention de la DERNIÈRE clause a été coupée par le plafond d'union")


def test_la_fusion_a_tour_de_role_ne_coute_pas_les_composites(retriever):
    """Le tour de rôle ne doit pas défaire ce que le découpage avait gagné."""
    for requete, groupes in (
        ("lis le README et poste un résumé sur slack", ("filesystem", "slack")),
        ("cherche la météo de demain et envoie-la moi par mail", ("weather", "gmail")),
    ):
        outils = {t.name for t in retriever.get(requete)}
        for groupe in groupes:
            assert outils & set(TOOL_GROUPS[groupe].tools), \
                f"« {requete} » a perdu {groupe}"


# ── Porte de récurrence ───────────────────────────────────────────────────────
RECURRENTES = [
    "fais-moi un recap tous les jours a 14h", "rappelle moi dans 2 heures",
    "quotidiennement", "envoie-moi ça chaque jour", "vérifie périodiquement",
    "tous les jours à la même heure", "notifie-moi si le site tombe",
    "alerte si le disque se remplit", "automatiquement à heure fixe",
    "recurring task", "every morning", "surveille le dépôt",
]
PONCTUELLES = [
    "quelle heure est-il ?", "quel temps fait-il a paris",
    "envoie un message sur le canal test-cron", "lis le fichier src/main.py",
    "resume mes derniers mails", "y a-t-il de bons paris a faire ce soir",
    "mes rendez vous de demain", "montre moi le dernier commit",
]


@pytest.mark.parametrize("requete", RECURRENTES)
def test_chaque_formulation_recurrente_ouvre_la_porte(requete):
    assert _recurrence_intent(requete), f"récurrence non détectée : {requete!r}"


@pytest.mark.parametrize("requete", PONCTUELLES)
def test_aucune_demande_ponctuelle_n_ouvre_la_porte(requete):
    """« le canal test-cron » est un nom de canal Slack, pas une planification :
    c'est pourquoi la porte exige `(?<![\\w-])cron`."""
    assert not _recurrence_intent(requete), f"faux positif : {requete!r}"


def test_la_porte_de_recurrence_ne_depend_pas_de_l_embedder():
    """Comme `_money_intent` : sa réponse doit être la même sur une machine sans
    Ollama. C'est ce qui en fait un filet et non un second classement."""
    import inspect

    from src.orchestrator import tool_retriever

    source = inspect.getsource(tool_retriever._recurrence_intent)
    for dependance in ("self", "_store", "similarity", "embed"):
        assert dependance not in source


def test_la_porte_de_recurrence_amene_l_outil_de_planification(retriever):
    """L'invariant qui justifie le mécanisme : `cron` passait de 64,5 % à 100 %
    de rappel sur ses 31 sondes."""
    for requete in ("fais-le tous les jours", "quotidiennement", "alerte si le disque se remplit"):
        outils = {t.name for t in retriever.get(requete)}
        assert outils & set(TOOL_GROUPS["cron"].tools), f"pas de planification pour {requete!r}"


def test_les_trois_portes_ajoutent_sans_jamais_retirer(retriever):
    """Une porte ADJOINT son groupe. « préviens-moi chaque matin sur Slack »
    doit garder Slack, sans quoi la porte échangerait un domaine contre un
    autre au lieu de compléter."""
    requete = "préviens-moi chaque matin sur slack"
    assert _recurrence_intent(requete)
    outils = {t.name for t in retriever.get(requete)}
    assert outils & set(TOOL_GROUPS["cron"].tools)
    assert outils & set(TOOL_GROUPS["slack"].tools), "la porte a évincé Slack"


def test_les_portes_couvrent_trois_intentions_distinctes():
    """Chacune reconnaît la sienne et ignore les deux autres — sans quoi elles
    se recouvriraient et la sélection enflerait sur toutes les requêtes."""
    assert _recurrence_intent("fais-le tous les jours")
    assert not _money_intent("fais-le tous les jours")
    assert _money_intent("combien miser sur ce combiné ?")
    assert not _recurrence_intent("combien miser sur ce combiné ?")
    assert _coding_intent("ajoute des tests unitaires")
    assert not _recurrence_intent("ajoute des tests unitaires")
