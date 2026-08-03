"""Injection des réponses du questionnaire dans l'état LangGraph.

Cas rapporté : le questionnaire s'affiche, l'utilisateur répond, puis le modèle repose
EXACTEMENT les mêmes questions et s'arrête. Cause : `add_messages` ne REMPLACE un message
que si l'`id` fourni correspond à un message déjà présent ; sinon il AJOUTE. Le
placeholder `{"awaiting_input": true}` restait donc dans l'état À CÔTÉ des réponses, et le
modèle lisait « en attente de réponse ».

Ces tests reproduisent le comportement du réducteur sur un vrai graph.
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
