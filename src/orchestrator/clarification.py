"""Le nœud qui pose les questions dont un outil déclare avoir besoin.

Un outil rend `status: CLARIFICATION_REQUIRED` et une liste `missing` ; ce nœud
pose les questions correspondantes et réinscrit l'échange dans l'historique.

Porte aussi `apres_les_outils`, l'arête qui arbitre entre les nœuds de demande.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage

from src.orchestrator.hitl import CLARIFICATION, Demande, Question, demander

#: Statut déclencheur. L'outil doit rendre ce statut ET une liste `missing`.
STATUT = "CLARIFICATION_REQUIRED"

#: Champ manquant → question posée. Les clients ajoutent « Autre » eux-mêmes :
#: ne pas l'inscrire dans les choix.
QUESTIONS: dict[str, dict[str, Any]] = {
    "bankroll": {
        "question": "Quelle est ta bankroll ? (capital en euros que tu alloues "
                    "aux paris, hors bonus et freebets)",
        "choices": ["50 €", "100 €", "200 €", "500 €"],
    },
}


def _charge(message: Any) -> dict | None:
    """Le JSON d'un `ToolMessage`, ou None si ce n'en est pas un."""
    if not isinstance(message, ToolMessage):
        return None
    contenu = message.content
    if not isinstance(contenu, str):
        return None
    try:
        charge = json.loads(contenu)
    except (ValueError, TypeError):
        return None
    return charge if isinstance(charge, dict) else None


def champs_manquants(message: Any) -> tuple[str, ...]:
    """Les champs manquants déclarés par ce résultat d'outil.

    Un champ absent de `QUESTIONS` est écarté : mieux vaut laisser le modèle
    expliquer le manque qu'ouvrir un questionnaire intitulé d'un nom de variable.
    """
    charge = _charge(message)
    if not charge or charge.get("status") != STATUT:
        return ()
    manquants = charge.get("missing") or ()
    if not isinstance(manquants, (list, tuple)):
        return ()
    return tuple(c for c in manquants if c in QUESTIONS)


def deja_demande(messages: list, champs: tuple[str, ...]) -> bool:
    """Ces questions ont déjà été posées sur ce fil.

    Garde anti-boucle : un modèle qui rappelle l'outil sans reporter la réponse
    relancerait sinon le questionnaire indéfiniment.
    """
    attendues = {QUESTIONS[c]["question"] for c in champs}
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            continue
        if getattr(message, "name", None) != "ask_clarification":
            continue
        contenu = message.content if isinstance(message.content, str) else ""
        if any(q[:40] in contenu for q in attendues):
            return True
        # Les réponses d'un questionnaire précédent portent la clé `answers` :
        # leur seule présence dit qu'on a déjà interrogé l'utilisateur sur ce fil.
        if '"answers"' in contenu:
            return True
    return False


def apres_les_outils(state: dict) -> str:
    """Quel nœud de demande suit le nœud d'outils, ou « chatbot ».

    Une seule demande peut être en vol par fil : `interrupt()` arrête le graphe,
    donc aucun second nœud ne s'exécute avant la réponse.
    """
    messages = state.get("messages") or []
    if not messages:
        return "chatbot"
    dernier = messages[-1]

    from src.orchestrator import confirmation

    champs = champs_manquants(dernier)
    if champs and not deja_demande(messages[:-1], champs):
        return "clarifier"

    if confirmation.commande_a_confirmer(dernier):
        return "confirmer"

    from src.orchestrator.revision import revision_attendue

    if revision_attendue(state):
        return "reviser"

    from src.orchestrator.envoi import envoi_attendu

    if envoi_attendu(state):
        return "envoyer"

    from src.agents.deep.noeud import question_a_creuser

    if question_a_creuser(dernier):
        return "approfondir"

    return "chatbot"


def clarifier(state: dict) -> dict:
    """Pose les questions, puis réinscrit l'échange dans l'historique.

    `interrupt()` rend la réponse au nœud, pas à la conversation : l'échange est
    réinscrit en appel d'outil + résultat, forme que le modèle et `deja_demande`
    savent relire.
    """
    champs = champs_manquants(state["messages"][-1])
    questions = tuple(
        Question(texte=QUESTIONS[c]["question"],
                 choix=tuple(QUESTIONS[c].get("choices") or ()))
        for c in champs)

    reponses = demander(Demande(genre=CLARIFICATION, cle=",".join(champs),
                                questions=questions))

    # ── À partir d'ici : une seule fois ─────────────────────────────────────
    identifiant = f"clarif_{uuid4().hex[:16]}"
    echange = {q.texte: r for q, r in zip(questions, reponses)}
    return {"messages": [
        AIMessage(content="", tool_calls=[{
            "name": "ask_clarification",
            "args": {"questions": [{"question": q.texte, "choices": list(q.choix)}
                                   for q in questions]},
            "id": identifiant,
        }]),
        ToolMessage(content=json.dumps({"answers": echange}, ensure_ascii=False),
                    tool_call_id=identifiant, name="ask_clarification"),
    ]}
