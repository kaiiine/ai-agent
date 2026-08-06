# src/orchestrator/resilience.py
"""Que faire quand ça échoue — sans que l'utilisateur perde son tour.

Deux pièces indépendantes du graphe : la traduction d'un échec d'outil en
résultat lisible par le modèle, et le journal qui rend les pannes mesurables.
La boucle de reprise de l'orchestrateur vit encore dans `graph.py` ; elle
rejoindra ce module quand elle sera couverte par des tests de comportement.
"""
from __future__ import annotations

import json

def _log_failure(backend: str, exc: Exception, strategy: str, recovered: bool) -> None:
    """Consigne l'échec pour que « ce backend est instable » devienne mesurable."""
    try:
        from src.infra.failure_log import record
        record(backend=backend, error_type=type(exc).__name__, message=str(exc),
               strategy=strategy, recovered=recovered)
    except Exception:
        pass

def tool_error_to_message(exc: Exception) -> str:
    """Transforme l'échec d'un outil en RÉSULTAT lisible par le modèle.

    Le handler par défaut de LangGraph ne rattrape que `ToolInvocationError`
    (arguments invalides) et re-lève tout le reste. Conséquence : une panne
    réseau, une clé absente ou un `KeyError` dans n'importe quel outil faisait
    remonter l'exception jusqu'à l'affichage et tuait le tour — l'utilisateur
    voyait « erreur : … » et perdait tout, sans que le modèle sache seulement
    qu'un outil avait échoué.

    Ici l'échec redevient une information : le modèle la lit, l'explique, et
    tente autre chose. C'est le comportement attendu d'un agent — un outil qui
    échoue est un fait du monde, pas un plantage du programme.

    `GraphBubbleUp` reste levée : ce n'est pas une erreur mais le mécanisme
    d'interruption de LangGraph (`interrupt()`, `Command`). L'avaler bloquerait
    les confirmations utilisateur. `KeyboardInterrupt` et `SystemExit` ne sont
    pas des `Exception` et ne passent donc jamais ici.
    """
    from langgraph.errors import GraphBubbleUp

    if isinstance(exc, GraphBubbleUp):
        raise exc

    return json.dumps({
        "status": "TOOL_ERROR",
        "error_type": type(exc).__name__,
        "message": str(exc) or "échec sans message",
        "note": "Cet outil a échoué. Ce n'est PAS un résultat : ne présente pas "
                "ce contenu comme une donnée. Explique brièvement l'échec, puis "
                "soit tente une autre approche, soit dis clairement que tu n'as "
                "pas pu aboutir. N'invente jamais le résultat attendu.",
    }, ensure_ascii=False)
