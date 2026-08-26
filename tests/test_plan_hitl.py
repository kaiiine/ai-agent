"""Le plan se valide dans le graphe, pas dans la boucle de flux.

Dernier producteur de HITL à migrer, et le seul déclenché par le TEXTE du modèle
— un bloc `<axon:plan>` — et non par un appel d'outil. Il s'intercale donc entre
`chatbot` et la fin du tour.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.orchestrator.hitl import PLAN, demande_en_attente, reponse
from src.orchestrator.plan import (
    ABANDONNER,
    EXECUTER,
    FERME,
    OUVERT,
    PRECISER,
    plan_a_valider,
    valider,
)


class _Etat(TypedDict):
    messages: Annotated[list, add_messages]


def _message_plan(corps="1. installer\n2. configurer"):
    return AIMessage(content=f"Voici mon plan :\n{OUVERT}\n{corps}\n{FERME}")


@pytest.fixture(autouse=True)
def mode_plan(monkeypatch):
    etat = {"actif": True}
    import src.ui.plan_mode as pm

    monkeypatch.setattr(pm, "is_active", lambda: etat["actif"])
    monkeypatch.setattr(pm, "set_active", lambda v: etat.__setitem__("actif", v))
    return etat


def _graphe():
    g = StateGraph(_Etat)
    g.add_node("valider_plan", valider)
    g.add_edge(START, "valider_plan")
    g.add_edge("valider_plan", END)
    return g.compile(checkpointer=MemorySaver())


# ── Quand demander ───────────────────────────────────────────────────────────
def test_un_bloc_plan_declenche_la_validation():
    assert plan_a_valider({"messages": [_message_plan()]})


@pytest.mark.parametrize("message", [
    AIMessage(content="une réponse ordinaire"),
    AIMessage(content=f"{OUVERT} sans fermeture"),
    AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}]),
    HumanMessage(content=f"{OUVERT}a{FERME}"),
])
def test_le_reste_ne_declenche_rien(message):
    assert not plan_a_valider({"messages": [message]})


def test_hors_mode_plan_rien_ne_se_declenche(mode_plan):
    """Un bloc plan dans une réponse ordinaire ne doit pas ouvrir un
    questionnaire que l'utilisateur n'attend pas."""
    mode_plan["actif"] = False
    assert not plan_a_valider({"messages": [_message_plan()]})


# ── Ce qui est montré ────────────────────────────────────────────────────────
def test_le_plan_est_montre_en_entier():
    app = _graphe()
    cfg = {"configurable": {"thread_id": "montre"}}
    sortie = app.invoke({"messages": [_message_plan("1. installer\n2. configurer")]}, cfg)

    demande = demande_en_attente(sortie)
    assert demande.genre == PLAN
    assert "installer" in demande.apercu and "configurer" in demande.apercu
    assert demande.questions[0].affirmatif == EXECUTER


# ── Les trois issues ─────────────────────────────────────────────────────────
def test_executer_quitte_le_mode_plan_et_lance(mode_plan):
    app = _graphe()
    cfg = {"configurable": {"thread_id": "exec"}}
    app.invoke({"messages": [_message_plan()]}, cfg)
    finale = app.invoke(reponse([EXECUTER, ""]), cfg)

    assert not mode_plan["actif"], "le mode plan doit se fermer avant l'exécution"
    assert "approuvé" in finale["messages"][-1].content.lower()


def test_preciser_GARDE_le_mode_plan(mode_plan):
    """On veut un plan révisé, pas une exécution : refermer le mode ici ferait
    exécuter le plan suivant sans le montrer."""
    app = _graphe()
    cfg = {"configurable": {"thread_id": "precise"}}
    app.invoke({"messages": [_message_plan()]}, cfg)
    finale = app.invoke(reponse([PRECISER, "ajoute une étape de tests"]), cfg)

    assert mode_plan["actif"], "le mode plan s'est refermé sur une révision"
    assert "tests" in finale["messages"][-1].content


def test_abandonner_quitte_le_mode_et_n_execute_rien(mode_plan):
    app = _graphe()
    cfg = {"configurable": {"thread_id": "abandon"}}
    app.invoke({"messages": [_message_plan()]}, cfg)
    finale = app.invoke(reponse([ABANDONNER, ""]), cfg)

    assert not mode_plan["actif"]
    texte = finale["messages"][-1].content.lower()
    assert "abandonné" in texte and "n'exécute rien" in texte


@pytest.mark.parametrize("decision", ["", "oui", "exécuter", "n'importe quoi"])
def test_seul_le_libelle_exact_lance_l_execution(mode_plan, decision):
    app = _graphe()
    cfg = {"configurable": {"thread_id": f"strict-{decision or 'vide'}"}}
    app.invoke({"messages": [_message_plan()]}, cfg)
    finale = app.invoke(reponse([decision, ""]), cfg)

    assert "approuvé" not in finale["messages"][-1].content.lower()


def test_la_decision_arrive_comme_une_entree_utilisateur():
    """Un `AIMessage` serait diffusé par le TUI et relu par le modèle comme son
    propre tour — le défaut trouvé en session sur l'envoi de mail."""
    from src.orchestrator.plan import note_pour_le_modele

    assert isinstance(note_pour_le_modele("x"), HumanMessage)
    assert not isinstance(note_pour_le_modele("x"), AIMessage)


# ── Le câblage ───────────────────────────────────────────────────────────────
def test_le_graphe_intercale_le_noeud_avant_la_fin():
    import inspect

    from src.orchestrator import graph as g

    source = inspect.getsource(g)
    assert 'g.add_node("valider_plan"' in source
    assert '"valider_plan": "valider_plan"' in source
    assert 'g.add_edge("valider_plan", "chatbot")' in source


def test_l_ancien_chemin_post_flux_a_disparu():
    """Deux mécanismes pour le même besoin, c'est celui qu'on vient de supprimer
    plus sa copie qui ne se déclencherait jamais."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "streaming.py").read_text()
    assert "review_plan" not in source
