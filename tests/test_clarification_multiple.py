"""Plusieurs `ask_clarification` d'un même souffle doivent tous être répondus.

Vécu à l'écran sur « y a-t-il de bons paris à faire en ce moment ? » : le modèle
émet TROIS appels, un seul questionnaire s'affiche — une question sur cinq — et
après la réponse le modèle recrache les quatre autres en texte libre.

La cause n'était pas le garde-fou anti-question-en-texte, qui se déclenchait
correctement sur ce texte. C'était l'appariement :

    `appel_clarification` rendait le PREMIER appel du lot
    `clarifier_appel` n'émettait qu'UN `ToolMessage`
    les deux autres restaient sans réponse → `appels_en_attente` vrai
    le graphe revenait au nœud, `messages[-1]` était le `ToolMessage`
    → plus aucun appel trouvé → `{}` → blocage

Le modèle, coincé, reposait ses questions autrement.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import src.orchestrator.clarification as clarification
from src.orchestrator.clarification import (
    appel_clarification, appels_clarification, appels_en_attente, clarifier_appel,
)


def _appel(identifiant: str, question: str) -> dict:
    return {"name": "ask_clarification", "id": identifiant,
            "args": {"questions": [{"question": question, "choices": []}]}}


@pytest.fixture
def lot() -> AIMessage:
    return AIMessage(content="", tool_calls=[
        _appel("c1", "Quelle bankroll ?"),
        _appel("c2", "Quels sports ?"),
        _appel("c3", "Quelle période ?"),
    ])


@pytest.fixture
def repond():
    """`demander` interrompt le graphe — ici on rend directement les réponses."""
    with patch.object(clarification, "demander",
                      lambda d: tuple(f"rép{i}" for i, _ in enumerate(d.questions))):
        yield


def test_tous_les_appels_du_lot_sont_vus(lot):
    assert [a["id"] for a in appels_clarification(lot)] == ["c1", "c2", "c3"]


def test_le_singulier_reste_le_premier(lot):
    """`appel_clarification` garde son contrat : les appelants existants ne
    changent pas de comportement."""
    assert appel_clarification(lot)["id"] == "c1"


def test_chaque_appel_recoit_sa_reponse(lot, repond):
    """Un fournisseur refuse un tour dont les paires appel/résultat sont
    déséquilibrées — c'est déjà écrit dans `appels_en_attente`."""
    sortie = clarifier_appel({"messages": [lot]})

    assert [m.tool_call_id for m in sortie["messages"]] == ["c1", "c2", "c3"]


def test_les_questions_fusionnent_en_un_seul_questionnaire(lot, repond):
    """Trois appels ne doivent pas faire trois questionnaires d'affilée."""
    sortie = clarifier_appel({"messages": [lot]})
    posees = json.loads(sortie["messages"][0].content)["answers"]

    assert list(posees) == ["Quelle bankroll ?", "Quels sports ?", "Quelle période ?"]


def test_plus_rien_nest_en_attente_apres_le_noeud(lot, repond):
    """L'invariant qui manquait : c'est lui qui bloquait le tour."""
    sortie = clarifier_appel({"messages": [lot]})

    assert not appels_en_attente({"messages": [lot] + sortie["messages"]})


def test_un_appel_deja_repondu_nest_pas_repose(lot, repond):
    """Au retour dans le nœud, seuls les appels SANS réponse comptent."""
    deja = ToolMessage(content='{"answers": {}}', tool_call_id="c1",
                       name="ask_clarification")

    sortie = clarifier_appel({"messages": [lot, deja]})

    assert [m.tool_call_id for m in sortie["messages"]] == ["c2", "c3"]


def test_le_porteur_est_cherche_en_remontant(lot, repond):
    """`messages[-1]` était un `ToolMessage` : le nœud ne trouvait plus le lot."""
    deja = ToolMessage(content='{"answers": {}}', tool_call_id="c1",
                       name="ask_clarification")

    assert clarifier_appel({"messages": [lot, deja]})["messages"]


def test_un_lot_sans_clarification_ne_produit_rien(repond):
    autre = AIMessage(content="", tool_calls=[
        {"name": "get_current_time", "id": "t1", "args": {}}])

    assert clarifier_appel({"messages": [autre]}) == {}


def test_une_question_vide_repond_a_tous_les_appels(repond):
    """Même le refus doit équilibrer les paires."""
    vide = AIMessage(content="", tool_calls=[
        {"name": "ask_clarification", "id": "v1", "args": {"questions": []}},
        {"name": "ask_clarification", "id": "v2", "args": {"questions": []}},
    ])

    sortie = clarifier_appel({"messages": [vide]})

    assert [m.tool_call_id for m in sortie["messages"]] == ["v1", "v2"]
