"""Injection des réponses du questionnaire dans l'état LangGraph.

Cas rapporté : le questionnaire s'affiche, l'utilisateur répond, puis le modèle repose
EXACTEMENT les mêmes questions et s'arrête. Cause : `add_messages` ne REMPLACE un message
que si l'`id` fourni correspond à un message déjà présent ; sinon il AJOUTE. Le
placeholder `{"awaiting_input": true}` restait donc dans l'état À CÔTÉ des réponses, et le
modèle lisait « en attente de réponse ».

Ces tests reproduisent le comportement du réducteur sur un vrai graph.

SECOND CAS, MÊME SYMPTÔME, AUTRE CAUSE — les réponses étaient parfaitement
injectées, et personne ne les lisait. Afficher le questionnaire oblige à sortir du
générateur `graph.stream()` ; ce `break` abandonne le run. Le superstep `tools`
est bien commité, mais le suivant n'est jamais planifié : `get_state().next` vaut
`()`, et la reprise par `graph.stream(None)` ne réveille aucun nœud — sans lever
la moindre erreur. L'UI retombait alors sur son repli, qui réinjectait le message
d'origine et relançait le tour depuis zéro : le modèle reposait ses questions,
hors questionnaire cette fois, et concluait « en attente de votre réponse ».

`update_state(..., as_node="tools")` réinscrit la mise à jour comme venant du
nœud d'outils, ce qui replanifie `chatbot`.
"""

from __future__ import annotations

import json
import pathlib

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

_TCID = "call_abc123"


class _State(TypedDict):
    messages: Annotated[list, add_messages]


def _graph():
    def node(state: _State):
        return {"messages": [
            AIMessage(content="", tool_calls=[
                {"name": "ask_clarification", "args": {"questions": ["Quel sport ?"]}, "id": _TCID}
            ]),
            ToolMessage(
                content=json.dumps({"questions": ["Quel sport ?"], "awaiting_input": True}),
                tool_call_id=_TCID, name="ask_clarification"),
        ]}

    g = StateGraph(_State)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=MemorySaver())


def _tool_msgs(graph, config):
    return [m for m in graph.get_state(config).values["messages"]
            if isinstance(m, ToolMessage) and m.tool_call_id == _TCID]


def _answers_msg(real_id=None):
    return ToolMessage(content=json.dumps({"answers": {"Quel sport ?": "tennis"}}),
                       tool_call_id=_TCID, name="ask_clarification", id=real_id)


def test_wrong_id_appends_instead_of_replacing():
    """Reproduit la panne : sans le VRAI id, le placeholder survit à côté des réponses."""
    graph = _graph()
    config = {"configurable": {"thread_id": "t1"}}
    graph.invoke({"messages": [HumanMessage(content="hello")]}, config)

    # id erroné (on passait le tool_call_id, qui n'est PAS un id de message)
    graph.update_state(config, {"messages": [_answers_msg(real_id=_TCID)]})

    msgs = _tool_msgs(graph, config)
    assert len(msgs) == 2, "le placeholder devrait subsister (c'est le bug)"
    assert any("awaiting_input" in m.content for m in msgs)   # le modèle voyait ça


def test_real_id_replaces_placeholder():
    """Avec le vrai id du message, le remplacement fonctionne."""
    graph = _graph()
    config = {"configurable": {"thread_id": "t2"}}
    graph.invoke({"messages": [HumanMessage(content="hello")]}, config)

    placeholder = _tool_msgs(graph, config)[0]
    graph.update_state(config, {"messages": [_answers_msg(real_id=placeholder.id)]})

    msgs = _tool_msgs(graph, config)
    assert len(msgs) == 1
    assert "answers" in msgs[0].content and "awaiting_input" not in msgs[0].content


def test_stale_placeholder_is_repaired_by_removal():
    """Filet de sécurité : même si l'ajout a eu lieu, on supprime le placeholder."""
    graph = _graph()
    config = {"configurable": {"thread_id": "t3"}}
    graph.invoke({"messages": [HumanMessage(content="hello")]}, config)
    graph.update_state(config, {"messages": [_answers_msg(real_id=_TCID)]})  # mauvais id

    stale = [m for m in _tool_msgs(graph, config) if "answers" not in m.content]
    assert stale, "pré-condition : un placeholder résiduel existe"
    graph.update_state(config, {"messages": [RemoveMessage(id=m.id) for m in stale]})

    msgs = _tool_msgs(graph, config)
    assert len(msgs) == 1
    assert "answers" in msgs[0].content          # le modèle ne voit QUE les réponses


# ── Reprise du run après le questionnaire ─────────────────────────────────────

_PLACEHOLDER = json.dumps({"questions": [{"question": "Bankroll ?"}], "awaiting_input": True})


def _graph_conversationnel():
    """Même topologie que l'orchestrateur : `chatbot` ⇄ `tools`.

    Le nœud `chatbot` restitue ce qu'il a lu des résultats d'outils : c'est ce qui
    permet de vérifier qu'il a vu les RÉPONSES et non le placeholder — et, avant
    cela, qu'il a seulement été rappelé.
    """
    def chatbot(state: _State):
        if not any(isinstance(m, ToolMessage) for m in state["messages"]):
            return {"messages": [AIMessage(content="", tool_calls=[
                {"name": "ask_clarification",
                 "args": {"questions": [{"question": "Bankroll ?"}]}, "id": _TCID}])]}
        lus = [str(m.content) for m in state["messages"] if isinstance(m, ToolMessage)]
        return {"messages": [AIMessage(content="LU:" + "|".join(lus))]}

    def tools(state: _State):
        return {"messages": [ToolMessage(content=_PLACEHOLDER, tool_call_id=_TCID,
                                         name="ask_clarification")]}

    g = StateGraph(_State)
    g.add_node("chatbot", chatbot)
    g.add_node("tools", tools)
    g.add_edge(START, "chatbot")
    g.add_conditional_edges(
        "chatbot",
        lambda s: "tools" if getattr(s["messages"][-1], "tool_calls", None) else END,
        {"tools": "tools", END: END},
    )
    g.add_edge("tools", "chatbot")
    return g.compile(checkpointer=MemorySaver())


def _cycle_ui(config, *, as_node: str | None):
    """Le cycle exact de l'UI : stream → break sur le questionnaire → injection
    des réponses → reprise avec `None`. Rend le graph et les textes rédigés APRÈS
    la reprise."""
    graph = _graph_conversationnel()
    entree = {"messages": [HumanMessage(content="conseille-moi un pari")]}
    apres_reprise: list[str] = []

    while True:
        reprise = False
        for msg, _meta in graph.stream(entree, config=config, stream_mode="messages"):
            if isinstance(msg, ToolMessage) and msg.name == "ask_clarification":
                placeholder = next(
                    m for m in reversed(graph.get_state(config).values["messages"])
                    if isinstance(m, ToolMessage) and m.tool_call_id == _TCID
                )
                reponses = ToolMessage(
                    content=json.dumps({"answers": {"Bankroll ?": "20"}}),
                    tool_call_id=_TCID, name="ask_clarification", id=placeholder.id)
                kwargs = {"as_node": as_node} if as_node else {}
                graph.update_state(config, {"messages": [reponses]}, **kwargs)
                reprise = True
                break
            if isinstance(msg, AIMessage) and entree is None and msg.content:
                apres_reprise.append(str(msg.content))
        if reprise:
            entree = None
            continue
        break
    return graph, apres_reprise


def test_le_break_du_stream_laisse_le_run_sans_suite():
    """La cause racine, isolée : interrompre le flux n'a pas planifié la suite."""
    graph = _graph_conversationnel()
    config = {"configurable": {"thread_id": "b1"}}
    for msg, _ in graph.stream({"messages": [HumanMessage(content="go")]},
                               config=config, stream_mode="messages"):
        if isinstance(msg, ToolMessage):
            break
    etat = graph.get_state(config)
    assert any(isinstance(m, ToolMessage) for m in etat.values["messages"]), \
        "le superstep tools EST commité — ce n'est pas lui qui manque"
    assert etat.next == (), "c'est la planification du nœud suivant qui est perdue"


def test_sans_as_node_la_reprise_ne_reveille_personne():
    """Reproduit la panne : réponses injectées, modèle jamais rappelé."""
    config = {"configurable": {"thread_id": "r1"}}
    graph, apres = _cycle_ui(config, as_node=None)

    assert graph.get_state(config).next == ()
    assert apres == [], "le modèle n'a pas tourné : les réponses ne servent à rien"


def test_avec_as_node_le_modele_relit_les_reponses():
    """Le correctif : `as_node` replanifie `chatbot`, qui lit les vraies réponses."""
    config = {"configurable": {"thread_id": "r2"}}
    graph, apres = _cycle_ui(config, as_node="tools")

    assert apres, "le modèle doit avoir été rappelé après les réponses"
    assert '"20"' in apres[-1]
    assert "awaiting_input" not in apres[-1], \
        "le modèle ne doit jamais relire « en attente de réponse »"
    assert graph.get_state(config).next == ()   # le tour est bien terminé


def test_l_ui_replanifie_bien_la_reprise():
    """Les deux tests ci-dessus prouvent le MÉCANISME ; celui-ci prouve que l'UI
    s'en sert. Sans lui, retirer `as_node` du site d'appel laisserait la suite
    verte et la panne intacte.

    Les DEUX `update_state` du bloc sont concernés : le second (nettoyage du
    placeholder résiduel) remettrait `next` à `()` et annulerait le premier.
    """
    source = pathlib.Path("src/ui/streaming.py").read_text(encoding="utf-8")
    debut = source.rindex('elif tool_name == "ask_clarification"')
    bloc = source[debut:source.index('elif tool_name == "run_coding_agent"', debut)]

    appels = bloc.count("graph.update_state(")
    assert appels >= 2, "le bloc questionnaire doit écrire l'état"
    assert bloc.count("as_node=") == appels, \
        "chaque update_state du questionnaire doit replanifier le nœud suivant"

    # Le repli ne doit plus relancer le tour depuis le message d'origine.
    assert "graph.invoke(_stream_input, config=config)" in source
    assert "graph.invoke(current_state, config=config)" not in source


def test_le_noeud_outils_de_l_ui_existe_dans_l_orchestrateur():
    """`as_node` est un nom en dur. Le renommer côté graph casserait la reprise en
    silence — la seule erreur possible étant celle qu'on vient de corriger."""
    from src.ui.streaming import _NOEUD_OUTILS

    source = pathlib.Path("src/orchestrator/graph.py").read_text(encoding="utf-8")
    assert f'add_node("{_NOEUD_OUTILS}"' in source


# ── Repli quand le flux n'a produit aucun jeton ────────────────────────────────

def test_le_repli_ignore_le_resultat_d_outil():
    """Le repli affichait `messages[-1]` tel quel. Après un questionnaire, c'est le
    résultat d'outil qui porte les réponses : l'utilisateur lisait son propre « 20 »
    en JSON à la place d'une réponse."""
    from src.ui.streaming import _dernier_texte_du_modele

    messages = [
        HumanMessage(content="conseille-moi un pari"),
        AIMessage(content="", tool_calls=[{"name": "ask_clarification", "args": {}, "id": _TCID}]),
        ToolMessage(content=json.dumps({"answers": {"Bankroll ?": "20"}}),
                    tool_call_id=_TCID, name="ask_clarification"),
        AIMessage(content="Voici ce que le moteur a retourné."),
    ]
    assert _dernier_texte_du_modele(messages) == "Voici ce que le moteur a retourné."


def test_le_repli_ne_remonte_pas_au_tour_precedent():
    """Sans réponse ce tour-ci, mieux vaut rien qu'une vieille réponse : elle
    passerait pour celle d'aujourd'hui."""
    from src.ui.streaming import _dernier_texte_du_modele

    messages = [
        HumanMessage(content="première question"),
        AIMessage(content="réponse du tour précédent"),
        HumanMessage(content="deuxième question"),
        AIMessage(content="", tool_calls=[{"name": "ask_clarification", "args": {}, "id": _TCID}]),
        ToolMessage(content=json.dumps({"answers": {}}), tool_call_id=_TCID,
                    name="ask_clarification"),
    ]
    assert _dernier_texte_du_modele(messages) == ""


# ── Cron : UN SEUL chemin d'envoi (le daemon), jamais l'agent ───────────────────
def test_cron_agent_has_no_sending_tool():
    """L'agent d'une tâche planifiée CALCULE et renvoie {notify, message} ; c'est le
    DAEMON qui publie via _send_notification. Donner un outil d'envoi à l'agent créerait
    un second chemin parallèle (risque de double publication)."""
    import re as _re
    src = pathlib.Path("src/cron_daemon.py").read_text()
    tools_block = _re.search(r"tools = \[(.*?)\]", src, _re.DOTALL).group(1)
    for forbidden in ("slack_send_message", "gmail_send_email", "notify,"):
        assert forbidden not in tools_block, f"{forbidden} ne doit pas être un outil de l'agent cron"
    # le daemon, lui, garde bien sa diffusion
    assert "_send_notification(task[" in src and "_notify_slack" in src


def test_schedule_task_documents_automatic_delivery():
    """Le modèle réclamait une URL de webhook : la docstring doit dire que l'envoi est
    automatique via notify_channels."""
    from src.agents.cron.tools import schedule_task

    doc = (schedule_task.description or "").lower()
    assert "automatique" in doc
    assert "webhook" in doc          # interdiction explicite de la demander
