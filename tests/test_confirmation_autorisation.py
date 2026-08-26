"""L'accord de l'utilisateur, demandé par le graphe — et le graphe s'arrête.

Ce fichier remplace `test_slot_confirmation.py`, dont la moitié gardait un slot
process-side qui n'existe plus. Ce n'est pas un relâchement : la garantie « un
seul questionnaire en vol » est passée du code applicatif au moteur. `interrupt()`
ARRÊTE le graphe, et un fil ne peut porter qu'une interruption à la fois.

Les tests qui gardaient la mécanique du slot — réservation, libération par un
tour étranger, péremption — sont supprimés parce que ce qu'ils protégeaient a
disparu. Ceux qui gardaient une GARANTIE sont conservés et réexprimés ici : un
refus n'autorise rien, un accord réémet l'appel, l'aperçu est montré, et seul un
accord explicite vaut accord.
"""
from __future__ import annotations

import json
from typing import TypedDict

import pytest
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents.shell import autorisation
from src.orchestrator.confirmation import (
    NON,
    OUI,
    apres_confirmation,
    commande_a_confirmer,
    confirmer,
)
from src.orchestrator.hitl import AUTORISATION, demande_en_attente, reponse


@pytest.fixture(autouse=True)
def propre():
    autorisation.reinitialiser()
    yield
    autorisation.reinitialiser()


def _demande(commande="rm -rf /tmp/x", **extra):
    charge = {"status": "requires_confirmation", "command": commande,
              "reason": "destructive", **extra}
    return ToolMessage(content=json.dumps(charge), tool_call_id="tc", name="shell_run")


class _Etat(TypedDict):
    messages: list


def _graphe():
    """Le nœud de confirmation, dans un graphe minimal mais RÉEL.

    Réel importe : `interrupt()` n'a de sens qu'exécuté par le moteur, avec un
    checkpointer. Appeler `confirmer()` à la main testerait une fonction, pas le
    comportement qu'on cherche à garantir.
    """
    def rien(state):
        return {}

    g = StateGraph(_Etat)
    g.add_node("confirmer", confirmer)
    g.add_node("tools", rien)
    g.add_node("chatbot", rien)
    g.add_edge(START, "confirmer")
    g.add_conditional_edges("confirmer", apres_confirmation,
                            {"tools": "tools", "chatbot": "chatbot"})
    g.add_edge("tools", END)
    g.add_edge("chatbot", END)
    return g.compile(checkpointer=MemorySaver())


# ── Lecture de la demande ────────────────────────────────────────────────────
def test_seul_un_statut_de_confirmation_declenche_la_demande():
    assert commande_a_confirmer(_demande()) == "rm -rf /tmp/x"
    assert commande_a_confirmer(ToolMessage(
        content=json.dumps({"status": "ok"}), tool_call_id="t", name="shell_run")) is None
    assert commande_a_confirmer(ToolMessage(
        content="pas du json", tool_call_id="t", name="shell_run")) is None


# ── Le graphe s'arrête vraiment ──────────────────────────────────────────────
def test_le_graphe_s_arrete_et_montre_la_commande(tmp_path):
    app = _graphe()
    cfg = {"configurable": {"thread_id": "arret"}}

    sortie = app.invoke({"messages": [_demande()]}, cfg)
    demande = demande_en_attente(sortie)

    assert demande is not None, "le graphe n'a pas marqué de pause"
    assert demande.genre == AUTORISATION
    assert demande.cle == "rm -rf /tmp/x"
    assert "rm -rf /tmp/x" in demande.questions[0].texte, "la commande doit être MONTRÉE"
    assert demande.questions[0].affirmatif == OUI


def test_l_apercu_d_ecriture_voyage_a_part():
    """Approuver une écriture sans voir ce qu'elle écrit, c'est approuver un
    effet inconnu. Mais un diff n'a pas à être aplati dans un libellé : il a son
    champ, que les clients rendent comme ils veulent."""
    app = _graphe()
    cfg = {"configurable": {"thread_id": "apercu"}}
    sortie = app.invoke({"messages": [_demande(
        'ssh vps "cat > /etc/motd"', host="vps",
        preview="Fichier : /etc/motd\nMode : écrasement")]}, cfg)

    demande = demande_en_attente(sortie)
    assert "/etc/motd" in demande.apercu
    assert "vps" in demande.questions[0].texte
    assert demande.extra.get("host") == "vps"


def test_une_seule_demande_en_vol_par_fil():
    """La garantie qui était portée par le slot. Elle est maintenant portée par
    le moteur : tant qu'une interruption n'est pas résolue, le fil ne progresse
    pas, donc aucune seconde demande ne peut naître."""
    app = _graphe()
    cfg = {"configurable": {"thread_id": "unique"}}

    sortie = app.invoke({"messages": [_demande()]}, cfg)
    assert len(sortie.get("__interrupt__") or []) == 1

    # Relancer sans répondre ne crée pas de seconde demande.
    encore = app.invoke(None, cfg)
    assert len(encore.get("__interrupt__") or []) == 1
    assert demande_en_attente(encore).cle == "rm -rf /tmp/x"


# ── La décision ──────────────────────────────────────────────────────────────
def test_un_accord_autorise_et_reemet_l_appel():
    app = _graphe()
    cfg = {"configurable": {"thread_id": "accord"}}
    app.invoke({"messages": [_demande()]}, cfg)

    finale = app.invoke(reponse([OUI]), cfg)
    dernier = finale["messages"][-1]

    assert dernier.tool_calls[0]["name"] == "shell_run"
    assert dernier.tool_calls[0]["args"]["command"] == "rm -rf /tmp/x", (
        "la commande réémise doit être celle qui a été montrée")
    assert apres_confirmation({"messages": [dernier]}) == "tools"


def test_un_refus_n_autorise_rien_et_ne_reemet_rien():
    app = _graphe()
    cfg = {"configurable": {"thread_id": "refus"}}
    app.invoke({"messages": [_demande()]}, cfg)

    finale = app.invoke(reponse([NON]), cfg)
    dernier = finale["messages"][-1]

    assert not autorisation.est_autorisee("rm -rf /tmp/x"), "un refus a autorisé"
    assert not getattr(dernier, "tool_calls", None)
    assert apres_confirmation({"messages": [dernier]}) == "chatbot", (
        "un message sans appel envoyé au nœud d'outils planterait le tour")


@pytest.mark.parametrize("reponse_client, attendu", [
    (OUI, True), (NON, False), ("", False), ("oui", False), ("peut-être", False),
])
def test_seul_le_libelle_affirmatif_vaut_accord(reponse_client, attendu):
    """Un client qui échoue, une fenêtre fermée ou une réponse vide ne doivent
    pas produire un accord que personne n'a donné."""
    app = _graphe()
    cfg = {"configurable": {"thread_id": f"binaire-{reponse_client or 'vide'}"}}
    app.invoke({"messages": [_demande("rm -rf /tmp/zzz")]}, cfg)
    app.invoke(reponse([reponse_client]), cfg)

    assert autorisation.est_autorisee("rm -rf /tmp/zzz") is attendu


def test_l_accord_n_est_inscrit_qu_UNE_fois_malgre_le_rejeu():
    """LangGraph rejoue le nœud à la reprise. Si `accorder()` était placé avant
    l'interruption, il s'exécuterait deux fois — et l'autorisation, à usage
    unique, serait consommée par le rejeu avant d'avoir servi."""
    app = _graphe()
    cfg = {"configurable": {"thread_id": "rejeu"}}
    app.invoke({"messages": [_demande("rm -rf /tmp/unique")]}, cfg)
    app.invoke(reponse([OUI]), cfg)

    assert autorisation.est_autorisee("rm -rf /tmp/unique"), "l'accord n'a pas survécu"
    assert not autorisation.est_autorisee("rm -rf /tmp/unique"), "usage unique perdu"
