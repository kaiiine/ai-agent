"""L'agent de code comme sous-graphe : ce que la boucle ne pouvait pas offrir.

Il tournait dans une boucle ordinaire à l'intérieur d'un outil, et un outil est
atomique pour le moteur : interrompre depuis là rejoue tout son travail. Mesuré —
une étape déjà faite s'exécutait DEUX fois à la reprise. C'est pour ça qu'il ne
demandait jamais rien, qu'il ne pouvait rien supprimer, et qu'il rejouait trois
fois la même commande refusée.

Ces tests tiennent les quatre choses que la migration devait rendre possibles.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from typing_extensions import TypedDict

import pytest

from src.agents.coding.graphe_agent import (
    MARQUEUR_DELEGATION, construire, consignes_en_attente, rediriger,
)
from src.agents.coding.pending import dev_plan


@lc_tool("lire")
def lire(quoi: str) -> str:
    """Lit."""
    return f"contenu de {quoi}"


class _Parent(TypedDict, total=False):
    messages: list


def _sous_un_outil(sous_graphe):
    """Le vrai montage : le sous-graphe est invoqué depuis un OUTIL.

    C'est la configuration qui compte — un outil est atomique, et c'est là que le
    rejeu se produisait.
    """
    @lc_tool("agent_code")
    def agent_code(tache: str) -> str:
        """Délègue."""
        return str(sous_graphe.invoke({"tache": tache}).get("resultat"))

    def chatbot(etat):
        if any(isinstance(m, AIMessage) for m in etat["messages"]):
            return {"messages": []}
        return {"messages": [AIMessage("", tool_calls=[
            {"name": "agent_code", "id": "1", "args": {"tache": "range"}}])]}

    g = StateGraph(_Parent)
    g.add_node("chatbot", chatbot)
    g.add_node("outils", ToolNode([agent_code]))
    g.add_edge(START, "chatbot")
    g.add_conditional_edges("chatbot", lambda e: "outils" if getattr(
        e["messages"][-1], "tool_calls", None) else END, {"outils": "outils", END: END})
    g.add_edge("outils", END)
    return g.compile(checkpointer=MemorySaver())


def _interruptions(parent, cfg):
    instantane = parent.get_state(cfg)
    return [i for t in (instantane.tasks or ()) for i in (t.interrupts or ())]


@pytest.fixture(autouse=True)
def _plan_propre():
    dev_plan.clear()
    yield
    dev_plan.clear()


# ── 1. demander en plein travail, sans tout rejouer ──────────────────────────
def test_une_confirmation_ne_rejoue_pas_le_travail_deja_fait():
    effets: list[str] = []
    refus = {"fait": False}

    def _enrichir(tache):
        effets.append("enrichir")          # un appel modèle : le rejouer se paie
        return tache

    tours = {"n": 0}

    def _appeler(messages, actifs, fournisseur):
        tours["n"] += 1
        if tours["n"] == 1:
            return AIMessage("", tool_calls=[{"name": "lire", "id": "a1",
                                              "args": {"quoi": "x"}}]), None, messages
        return AIMessage("fini"), None, messages

    def _executer(nom, args):
        effets.append("executer")
        if not refus["fait"]:
            refus["fait"] = True
            return {"status": "requires_confirmation", "command": "rm /tmp/x",
                    "message": "Commande DESTRUCTIVE : rm /tmp/x", "reason": "destructive"}
        return {"status": "ok"}

    parent = _sous_un_outil(construire(
        outils=[lire], selectionner=lambda m, t: [lire], appeler_modele=_appeler,
        enrichir=_enrichir, prompt_systeme="", executer=_executer, tracer=lambda m: ""))

    cfg = {"configurable": {"thread_id": "t-conf"}}
    parent.invoke({"messages": [HumanMessage("vas-y")]}, cfg)

    demandes = _interruptions(parent, cfg)
    assert demandes, "l'agent doit pouvoir demander"
    assert demandes[0].value.get("genre") == "autorisation"
    assert demandes[0].value.get("cle") == "rm /tmp/x"

    parent.invoke(Command(resume=["Oui, exécuter"]), cfg)
    assert effets.count("enrichir") == 1, effets


def test_un_refus_ne_relance_pas_la_commande():
    tours = {"n": 0}

    def _appeler(messages, actifs, fournisseur):
        tours["n"] += 1
        if tours["n"] == 1:
            return AIMessage("", tool_calls=[{"name": "lire", "id": "a1",
                                              "args": {"quoi": "x"}}]), None, messages
        return AIMessage("compris"), None, messages

    appels = {"n": 0}

    def _executer(nom, args):
        appels["n"] += 1
        return {"status": "requires_confirmation", "command": "rm -rf /",
                "message": "DESTRUCTIVE", "reason": "destructive"}

    parent = _sous_un_outil(construire(
        outils=[lire], selectionner=lambda m, t: [lire], appeler_modele=_appeler,
        enrichir=lambda t: t, prompt_systeme="", executer=_executer, tracer=lambda m: ""))

    cfg = {"configurable": {"thread_id": "t-refus"}}
    parent.invoke({"messages": [HumanMessage("vas-y")]}, cfg)
    parent.invoke(Command(resume=["Non, annuler"]), cfg)

    assert appels["n"] == 1, "un refus ne doit pas rejouer la commande"


# ── 2. interrompre et rediriger ──────────────────────────────────────────────
def test_une_consigne_deposee_en_route_est_lue_au_tour_suivant():
    """Sans point de reprise, une consigne arrivait après coup ou pas du tout."""
    vus: list[str] = []
    tours = {"n": 0}

    def _appeler(messages, actifs, fournisseur):
        tours["n"] += 1
        vus.extend(str(getattr(m, "content", "")) for m in messages)
        if tours["n"] == 1:
            rediriger("non, fais plutôt B")
            return AIMessage("", tool_calls=[{"name": "lire", "id": "a1",
                                              "args": {"quoi": "A"}}]), None, messages
        return AIMessage("je fais B"), None, messages

    construire(outils=[lire], selectionner=lambda m, t: [lire], appeler_modele=_appeler,
               enrichir=lambda t: t, prompt_systeme="", executer=lambda n, a: "ok",
               tracer=lambda m: "").invoke({"tache": "fais A"})

    assert consignes_en_attente() == 0, "la boîte doit être vidée"
    assert any("fais plutôt B" in v for v in vus)


# ── 3. plan visible et modifiable ────────────────────────────────────────────
def _graphe_avec_plan(reponses_modele):
    def _executer(nom, args):
        if nom == "dev_plan_create":
            dev_plan.create(args["steps"])
            return {"status": "ok"}
        return "fait"

    return construire(outils=[lire], selectionner=lambda m, t: [lire],
                      appeler_modele=reponses_modele, enrichir=lambda t: t,
                      prompt_systeme="", executer=_executer, tracer=lambda m: "")


def test_le_plan_est_soumis_avant_detre_suivi():
    tours = {"n": 0}

    def _appeler(messages, actifs, fournisseur):
        tours["n"] += 1
        if tours["n"] == 1:
            return AIMessage("", tool_calls=[{"name": "dev_plan_create", "id": "p1",
                                              "args": {"steps": ["lire", "écrire"]}}]), None, messages
        return AIMessage("terminé"), None, messages

    parent = _sous_un_outil(_graphe_avec_plan(_appeler))
    cfg = {"configurable": {"thread_id": "t-plan"}}
    parent.invoke({"messages": [HumanMessage("vas-y")]}, cfg)

    demandes = _interruptions(parent, cfg)
    assert demandes, "le plan doit être soumis"
    valeur = demandes[0].value
    assert valeur.get("genre") == "plan"
    assert "1. lire" in str(valeur.get("apercu"))
    assert "2. écrire" in str(valeur.get("apercu"))

    parent.invoke(Command(resume=["Exécuter", ""]), cfg)
    assert not _interruptions(parent, cfg), "un plan validé ne se redemande pas"


def test_un_plan_inchange_nest_pas_redemande_a_chaque_pas():
    tours = {"n": 0}

    def _appeler(messages, actifs, fournisseur):
        tours["n"] += 1
        if tours["n"] == 1:
            return AIMessage("", tool_calls=[{"name": "dev_plan_create", "id": "p1",
                                              "args": {"steps": ["a", "b"]}}]), None, messages
        if tours["n"] <= 3:
            return AIMessage("", tool_calls=[{"name": "lire", "id": f"t{tours['n']}",
                                              "args": {"quoi": "x"}}]), None, messages
        return AIMessage("terminé"), None, messages

    parent = _sous_un_outil(_graphe_avec_plan(_appeler))
    cfg = {"configurable": {"thread_id": "t-plan2"}}
    parent.invoke({"messages": [HumanMessage("vas-y")]}, cfg)
    parent.invoke(Command(resume=["Exécuter", ""]), cfg)

    assert not _interruptions(parent, cfg)
    assert tours["n"] >= 4, "le travail doit se poursuivre après validation"


# ── 4. sous-agents délégués ──────────────────────────────────────────────────
def test_lexploration_deleguee_rend_UN_rapport():
    """La délégation n'accélère rien : elle DÉCHARGE le contexte. Le modèle
    reçoit un compte rendu, pas les vingt lectures qui l'ont produit."""
    explores: list[str] = []
    tours = {"n": 0}

    def _appeler(messages, actifs, fournisseur):
        if "Tu explores un point précis" in str(getattr(messages[0], "content", "")):
            sujet = str(getattr(messages[1], "content", ""))
            explores.append(sujet)
            return AIMessage(f"rapport sur {sujet}"), None, messages
        tours["n"] += 1
        if tours["n"] == 1:
            return AIMessage("", tool_calls=[{"name": "deleguer", "id": "d1", "args": {
                "taches": ["où est le routeur", "où sont les tests"]}}]), None, messages
        return AIMessage("j'ai ce qu'il me faut"), None, messages

    def _executer(nom, args):
        if nom == "deleguer":
            return {"status": MARQUEUR_DELEGATION, "taches": args["taches"]}
        return lire.invoke(args)

    sortie = construire(
        outils=[lire], selectionner=lambda m, t: [lire], appeler_modele=_appeler,
        enrichir=lambda t: t, prompt_systeme="", executer=_executer,
        tracer=lambda m: "", outils_exploration=[lire]).invoke({"tache": "comprends"})

    assert explores == ["où est le routeur", "où sont les tests"]
    rapports = [m for m in sortie["messages"]
                if isinstance(m, ToolMessage) and m.name == MARQUEUR_DELEGATION]
    assert len(rapports) == 1, "un appel, une réponse"
    assert "où est le routeur" in str(rapports[0].content)
    assert "où sont les tests" in str(rapports[0].content)


def test_une_exploration_ne_peut_pas_ecrire():
    """Elle tourne sous `Send`, où une interruption ne remonte pas proprement :
    rien qui puisse exiger un accord ne doit y être atteignable."""
    refuses: list[str] = []

    def _appeler(messages, actifs, fournisseur):
        if "Tu explores un point précis" in str(getattr(messages[0], "content", "")):
            deja = [m for m in messages if isinstance(m, ToolMessage)]
            if deja:
                refuses.append(str(deja[-1].content))
                return AIMessage("je m'arrête"), None, messages
            return AIMessage("", tool_calls=[{"name": "ecrire", "id": "e1",
                                              "args": {}}]), None, messages
        if not any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage("", tool_calls=[{"name": "deleguer", "id": "d1",
                                              "args": {"taches": ["essaie d'écrire"]}}]), None, messages
        return AIMessage("fini"), None, messages

    def _executer(nom, args):
        if nom == "deleguer":
            return {"status": MARQUEUR_DELEGATION, "taches": args["taches"]}
        return "ÉCRITURE EFFECTUÉE"

    construire(outils=[lire], selectionner=lambda m, t: [lire], appeler_modele=_appeler,
               enrichir=lambda t: t, prompt_systeme="", executer=_executer,
               tracer=lambda m: "", outils_exploration=[lire]).invoke({"tache": "x"})

    assert refuses, "l'exploration doit recevoir un refus"
    assert "ÉCRITURE EFFECTUÉE" not in refuses[0]
    assert "exploration" in refuses[0]


def test_un_lot_mixte_reprend_au_bon_appel_apres_accord():
    """Après la confirmation, l'état se termine par les réponses déjà obtenues :
    lire `messages[-1]` ferait perdre les appels restants du même lot."""
    executes: list[str] = []
    tours = {"n": 0}

    def _appeler(messages, actifs, fournisseur):
        tours["n"] += 1
        if tours["n"] == 1:
            return AIMessage("", tool_calls=[
                {"name": "lire", "id": "ok1", "args": {"quoi": "A"}},
                {"name": "lire", "id": "danger", "args": {"quoi": "B"}},
            ]), None, messages
        return AIMessage("fini"), None, messages

    def _executer(nom, args):
        executes.append(args["quoi"])
        if args["quoi"] == "B" and executes.count("B") == 1:
            return {"status": "requires_confirmation", "command": "rm B",
                    "message": "DESTRUCTIVE : rm B", "reason": "destructive"}
        return {"status": "ok"}

    parent = _sous_un_outil(construire(
        outils=[lire], selectionner=lambda m, t: [lire], appeler_modele=_appeler,
        enrichir=lambda t: t, prompt_systeme="", executer=_executer, tracer=lambda m: ""))

    cfg = {"configurable": {"thread_id": "t-mixte"}}
    parent.invoke({"messages": [HumanMessage("vas-y")]}, cfg)
    assert _interruptions(parent, cfg), "B doit demander"
    parent.invoke(Command(resume=["Oui, exécuter"]), cfg)

    assert executes.count("A") == 1, f"A ne doit pas être rejoué : {executes}"
    assert executes.count("B") == 2, f"B : refus puis exécution : {executes}"


def test_un_accord_est_bien_lu_comme_un_accord():
    """`hitl.accorde` n'accepte le libellé affiché que si on lui passe la
    Question. Sans elle, « Oui, exécuter » valait REFUS — l'agent obtenait la
    permission et annonçait quand même un refus à l'utilisateur."""
    from src.orchestrator import hitl

    question = hitl.Question(texte="?", choix=("Non, annuler", "Oui, exécuter"),
                             affirmatif="Oui, exécuter")
    assert hitl.accorde("Oui, exécuter", question)
    assert not hitl.accorde("Non, annuler", question)
    assert not hitl.accorde("Oui, exécuter"), "sans la Question, rien ne vaut accord"
