"""Le catalogue promet trois choses ; chacune casse silencieusement si on la lâche.

1. Un nom lu au catalogue est appelable. Sinon le modèle réclame un outil, reçoit
   une confirmation, l'appelle — et le graphe répond « outil inconnu ». C'est le
   piège dans lequel je suis tombé en écrivant la pièce : le modèle voit les outils
   liés à chaque tour, mais le `ToolNode` est construit UNE fois au démarrage.
2. Un nom inventé est refusé. Le catalogue existe pour que le modèle cesse de
   deviner ; s'il peut ouvrir n'importe quoi, il devine de nouveau.
3. Le mode plan tient. Il retire les outils d'écriture de la sélection — les
   réclamer par leur nom rouvrirait la porte qu'il vient de fermer.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.orchestrator.catalogue import (
    OUVERTURES_MAX, connu, indexer, menu, obtenir_outil, outil, ouverts,
)
from src.orchestrator.registry import build_all_tools
from src.ui.plan_mode import BLOCKED_TOOLS


def _reclamer(nom: str) -> str:
    return obtenir_outil.invoke({"nom": nom})


@pytest.fixture(scope="module", autouse=True)
def _indexe():
    indexer(build_all_tools())


def test_tout_nom_du_catalogue_est_resolvable():
    manquants = [l.split(":", 1)[0] for l in menu().splitlines()
                 if outil(l.split(":", 1)[0]) is None]
    assert not manquants, f"nommés au catalogue mais introuvables : {manquants}"


def test_obtenir_outil_est_execute_par_le_graphe():
    """Sans ça, l'ouverture réussit côté modèle et échoue côté exécution."""
    from src.orchestrator.graph import _chat_node_factory

    _, tools = _chat_node_factory()
    assert "obtenir_outil" in {t.name for t in tools}


def test_un_nom_invente_est_refuse():
    reponse = _reclamer("gmail_envoyer_le_mail")
    assert "ne figure pas au catalogue" in reponse
    assert not connu("gmail_envoyer_le_mail")


def test_un_nom_du_catalogue_est_accepte():
    assert "disponible" in _reclamer("get_weather_by_city")


def test_le_catalogue_ne_se_propose_pas_lui_meme():
    assert "obtenir_outil:" not in menu()


def test_le_mode_plan_ne_laisse_pas_reclamer_une_ecriture():
    ligne_de_menu = {l.split(":", 1)[0] for l in menu(BLOCKED_TOOLS).splitlines()}
    assert not (ligne_de_menu & BLOCKED_TOOLS)


def test_le_refus_du_mode_plan_vient_de_loutil_pas_du_menu(monkeypatch):
    """Le menu cache ; l'outil interdit. Un modèle qui garde un nom en mémoire
    d'un tour précédent ne doit pas passer sous la barrière."""
    import src.ui.plan_mode as pm

    ecriture = sorted(BLOCKED_TOOLS & {l.split(":", 1)[0] for l in menu().splitlines()})[0]
    monkeypatch.setattr(pm, "is_active", lambda: True)
    assert "mode plan" in _reclamer(ecriture)


def test_ouverts_ne_deborde_pas_sur_le_tour_precedent():
    messages = [
        AIMessage("", tool_calls=[{"name": "obtenir_outil", "id": "0",
                                   "args": {"nom": "gmail_search"}}]),
        HumanMessage("autre chose"),
        AIMessage("", tool_calls=[{"name": "obtenir_outil", "id": "1",
                                   "args": {"nom": "notify"}}]),
    ]
    assert ouverts(messages) == ["notify"]


def test_ouverts_est_plafonne():
    noms = [l.split(":", 1)[0] for l in menu().splitlines()[: OUVERTURES_MAX + 3]]
    messages = [HumanMessage("va")] + [
        AIMessage("", tool_calls=[{"name": "obtenir_outil", "id": str(i),
                                   "args": {"nom": n}}])
        for i, n in enumerate(noms)
    ]
    assert len(ouverts(messages)) == OUVERTURES_MAX


def test_le_catalogue_reste_dans_son_budget():
    """~20 tokens par outil. Une ligne qui déborde, c'est une description dont la
    première ligne est un paragraphe — le catalogue redevient alors des schémas."""
    lignes = menu().splitlines()
    trop_longues = [l for l in lignes if len(l) > 160]
    assert not trop_longues, trop_longues[:3]
    assert len(menu()) // 4 < 40 * len(lignes)


def test_le_noeud_pose_le_catalogue_puis_lie_loutil_reclame(monkeypatch):
    """Le chemin complet sans réseau : le catalogue arrive dans le prompt, et un
    outil que le retriever n'aurait jamais servi devient lié parce qu'il a été
    réclamé au tour d'avant."""
    import src.orchestrator.graph as graphe

    capture: dict = {}

    class _Lie:
        def __init__(self, outils):
            capture["outils"] = {t.name for t in outils}

        def invoke(self, messages, *a, **k):
            capture["systeme"] = messages[0].content
            return AIMessage("ok")

    class _LLM:
        def bind_tools(self, outils, **k):
            return _Lie(outils)

        def invoke(self, messages, *a, **k):
            return _Lie([]).invoke(messages)

    for fabrique in ("make_llm", "make_llm_groq", "make_llm_ollama_cloud",
                     "make_llm_gemini", "make_llm_mistral", "make_llm_nvidia"):
        monkeypatch.setattr(graphe, fabrique, lambda *a, **k: _LLM())

    chatbot, _ = graphe._chat_node_factory()
    meteo = [HumanMessage("il va pleuvoir demain à Suresnes ?")]

    chatbot({"messages": meteo})
    assert "obtenir_outil" in capture["outils"]
    assert "━━ CATALOGUE ━━" in capture["systeme"]
    assert "get_weather_by_city:" in capture["systeme"]
    assert "jira_create_issue" not in capture["outils"], "témoin invalide"

    chatbot({"messages": meteo + [
        AIMessage("", tool_calls=[{"name": "obtenir_outil", "id": "1",
                                   "args": {"nom": "jira_create_issue"}}]),
    ]})
    assert "jira_create_issue" in capture["outils"]


def test_le_mode_plan_refuse_a_lexecution_pas_seulement_a_la_liaison(monkeypatch):
    """Le catalogue donne au modèle tous les noms d'outils. Il en appelle alors
    qui ne lui sont pas liés — vérifié sur gpt-oss:120b. Le mode plan ne peut
    donc plus reposer sur l'omission : il doit refuser au point d'exécution."""
    import src.ui.plan_mode as pm
    from src.orchestrator.tool_node import _refus_mode_plan

    ecriture = sorted(BLOCKED_TOOLS)[0]
    appels = [{"name": ecriture, "id": "1", "args": {}},
              {"name": "get_current_time", "id": "2", "args": {}}]

    monkeypatch.setattr(pm, "is_active", lambda: False)
    assert _refus_mode_plan(appels) == []

    monkeypatch.setattr(pm, "is_active", lambda: True)
    refus = _refus_mode_plan(appels)
    assert [m.tool_call_id for m in refus] == ["1"], "la lecture doit passer"
    assert "mode plan" in refus[0].content
    assert refus[0].status == "error"
