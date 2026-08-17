# src/orchestrator/resilience.py
"""Que faire quand ça échoue — sans que l'utilisateur perde son tour.

Deux pièces indépendantes du graphe : la traduction d'un échec d'outil en
résultat lisible par le modèle, et le journal qui rend les pannes mesurables.
La boucle de reprise de l'orchestrateur vit encore dans `graph.py` ; elle
rejoindra ce module quand elle sera couverte par des tests de comportement.
"""
from __future__ import annotations

import json

def _message_sur(exc: Exception) -> str:
    """Le message d'une exception, secrets masqués.

    Mesuré : les exceptions de `requests` embarquent l'URL COMPLÈTE, paramètres
    compris. Une clé passée en query string ressortait donc intégralement —

        Max retries exceeded with url: /v4/matches?apiKey=CLE_SECRETE_ABC123

    — et de là dans le contexte du modèle, donc chez le fournisseur LLM, et dans
    le journal des échecs sur disque.

    La rédaction est appliquée TOUJOURS, sans regarder le backend, là où
    `redactor.should_redact()` ne la réserve qu'aux backends cloud. La distinction
    est volontaire : ce garde-là protège des RÉSULTATS d'outils, où masquer
    pourrait détruire ce que l'utilisateur a justement demandé à lire. Un message
    d'erreur n'a pas ce besoin — « auth failed for key *** » informe le modèle
    exactement autant que la clé en clair.
    """
    from src.infra.redactor import redact
    return redact(str(exc) or "échec sans message")


def _log_failure(backend: str, exc: Exception, strategy: str, recovered: bool) -> None:
    """Consigne l'échec pour que « ce backend est instable » devienne mesurable."""
    try:
        from src.infra.failure_log import record
        record(backend=backend, error_type=type(exc).__name__,
               message=_message_sur(exc),
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

    Le message passe par `_message_sur`, qui masque les secrets : c'est ce chemin
    qui envoyait une clé d'API en clair au fournisseur LLM dès qu'un appel réseau
    échouait sur une URL en portant une.

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
        "message": _message_sur(exc),
        "note": "Cet outil a échoué. Ce n'est PAS un résultat : ne présente pas "
                "ce contenu comme une donnée. Explique brièvement l'échec, puis "
                "soit tente une autre approche, soit dis clairement que tu n'as "
                "pas pu aboutir. N'invente jamais le résultat attendu.",
    }, ensure_ascii=False)
