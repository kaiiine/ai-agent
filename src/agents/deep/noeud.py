"""Le nœud qui exécute une recherche approfondie.

Le sous-graphe est compilé SANS checkpointer : invoqué depuis un nœud, il hérite
de celui du parent. Ses étapes sont donc checkpointées — une recherche
interrompue reprend là où elle en était, sans refaire les appels déjà faits.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp

from src.orchestrator.note_interne import note

MARQUEUR = "recherche_approfondie_demandee"


def question_a_creuser(message: Any) -> str | None:
    """La question dont ce résultat d'outil demande l'approfondissement."""
    if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
        return None
    try:
        charge = json.loads(message.content)
    except (ValueError, TypeError):
        return None
    if not isinstance(charge, dict) or charge.get("status") != MARQUEUR:
        return None
    question = charge.get("question")
    return question if isinstance(question, str) and question.strip() else None


def approfondir(state: dict) -> dict:
    from src.agents.deep.graphe import construire
    from src.agents.deep.tools import chercher_web, repondre_avec_modele

    question = question_a_creuser(state["messages"][-1]) or ""
    if not question:
        return {"messages": []}

    try:
        sortie = construire(repondre_avec_modele(), chercher_web).invoke(
            {"question": question, "trouvailles": []})
    except GraphBubbleUp:
        # Une interruption n'est pas une erreur : c'est le sous-graphe qui
        # demande. L'attraper la transformerait en « la recherche a échoué ».
        raise
    except Exception as erreur:      # noqa: BLE001 — rapporté, jamais avalé
        return {"messages": [note(
            content=f"La recherche approfondie a échoué : {type(erreur).__name__}: "
                    f"{erreur}. Dis-le à l'utilisateur sans inventer de résultat.")]}

    rapport = (sortie.get("rapport") or "").strip()
    sujets = [t["sujet"] for t in sortie.get("trouvailles", [])]
    if not rapport:
        return {"messages": [note(
            content="La recherche approfondie n'a produit aucune synthèse.")]}

    return {"messages": [note(
        content=f"Résultat de la recherche approfondie sur « {question} » — "
                f"{len(sujets)} recherche(s) sur {sortie.get('tours', 1)} tour(s).\n\n"
                f"{rapport}\n\nRestitue-le à l'utilisateur sans rien y ajouter.")]}
