"""L'agent de code est un NŒUD du graphe principal, plus un outil.

Il tournait dans `run_coding_agent`. Un outil est atomique pour le moteur, et son
enveloppe est ré-entrée à chaque reprise :

    ['outil-entree', 'travail-lourd', 'outil-entree', 'apres-accord:oui']

L'étape checkpointée n'était pas rejouée, mais tout ce que l'enveloppe faisait
avant l'invocation l'était. Depuis un nœud, il n'y a plus d'enveloppe — même
motif que `deep_research` → `approfondir` : l'outil pose un marqueur, le routeur
donne la main au nœud.
"""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.coding.noeud import MARQUEUR, tache_a_coder


def _resultat(charge: dict) -> ToolMessage:
    return ToolMessage(content=json.dumps(charge), tool_call_id="rc1",
                       name="run_coding_agent")


def test_loutil_pose_un_marqueur_et_ne_travaille_pas():
    """Faire tourner l'agent dans l'outil l'enfermait dans un pas atomique."""
    from src.orchestrator.registry import run_coding_agent

    charge = json.loads(run_coding_agent.invoke(
        {"task": "corrige le bug de parsing dans src/main.py"}))
    assert charge["status"] == MARQUEUR
    assert charge["tache"].startswith("corrige le bug")


def test_une_tache_vide_est_refusee_sans_marqueur():
    from src.orchestrator.registry import run_coding_agent

    assert json.loads(run_coding_agent.invoke({"task": "court"}))["status"] == "error"


def test_le_marqueur_est_reconnu():
    assert tache_a_coder(_resultat({"status": MARQUEUR, "tache": "range"})) == "range"


def test_un_autre_resultat_nest_pas_confondu():
    assert tache_a_coder(_resultat({"status": "ok", "stdout": "rien"})) is None
    assert tache_a_coder(ToolMessage(content="pas du json", tool_call_id="x")) is None


def test_le_routeur_donne_la_main_au_noeud():
    from src.orchestrator.clarification import apres_les_outils

    etat = {"messages": [_resultat({"status": MARQUEUR, "tache": "range"})]}
    assert apres_les_outils(etat) == "coder"


def test_le_noeud_est_dans_le_graphe():
    from src.orchestrator.graph import build_orchestrator

    assert "coder" in build_orchestrator().get_graph().nodes


def test_une_interruption_nest_pas_avalee_par_le_rapport_derreur():
    """`except Exception` transformait la demande de confirmation en « l'agent de
    code a échoué », et l'utilisateur ne voyait jamais la question."""
    import inspect

    from langgraph.errors import GraphBubbleUp

    from src.agents.coding import noeud
    from src.agents.deep import noeud as noeud_deep

    for module in (noeud.coder, noeud_deep.approfondir):
        source = inspect.getsource(module)
        assert "GraphBubbleUp" in source, module.__name__
        assert source.index("except GraphBubbleUp") < source.index("except Exception")
    assert issubclass(GraphBubbleUp, Exception)


def test_le_noeud_rend_un_message_humain_pas_un_second_resultat_doutil(monkeypatch):
    """L'outil a déjà rendu le sien avec le marqueur : deux résultats pour un
    même appel déséquilibrent les paires, et le fournisseur refuse le tour.

    Le test portait sur le SOURCE (« HumanMessage( » y figure-t-il ?) : il est
    tombé le jour où le message est passé par un constructeur nommé, alors que le
    comportement, lui, n'avait pas bougé. On vérifie le message rendu."""
    import json

    from langchain_core.messages import HumanMessage, ToolMessage

    from src.agents.coding import noeud, specialist

    monkeypatch.setattr(specialist, "preparer", lambda t: (
        type("G", (), {"invoke": lambda s, e: {}})(), lambda r: "fait"))
    monkeypatch.setattr(specialist, "_vram_swap_in", lambda: None)
    monkeypatch.setattr(specialist, "_vram_swap_out", lambda: None)

    rendus = noeud.coder({"messages": [ToolMessage(
        content=json.dumps({"status": noeud.MARQUEUR, "tache": "écris tri.py"}),
        tool_call_id="c1", name="run_coding_agent")]})["messages"]

    assert len(rendus) == 1
    assert isinstance(rendus[0], HumanMessage)
    assert not isinstance(rendus[0], ToolMessage)


def test_le_noeud_passe_par_la_revue_avant_de_rendre_la_main():
    """L'agent de code dépose ses fichiers dans `pending_changes` et compte sur
    le nœud `reviser` — c'est écrit dans `_coding_progress`, mode `ask`.

    Une arête simple `coder → chatbot` laissait la proposition en plan : aucun
    diff, rien d'écrit, et le modèle redemandait confirmation d'un fichier que
    personne ne lui montrait. Trois questionnaires de suite, vécu."""
    from src.orchestrator.graph import build_orchestrator

    aretes = {(a.source, a.target) for a in build_orchestrator().get_graph().edges}
    assert ("coder", "reviser") in aretes
    assert ("coder", "chatbot") in aretes
