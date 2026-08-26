"""Poser la question nous-mêmes, plutôt que demander au modèle de la poser.

Un outil peut rendre « il me manque X ». Deux façons d'y donner suite :

  - écrire dans son résultat « appelle `ask_clarification` » et espérer ;
  - émettre l'appel d'outil soi-même.

La première a été essayée, et mesurée en échec : la consigne arrivait intacte
dans le résultat, et le modèle répondait en prose — « il me manque ta bankroll,
merci de me la communiquer » — puis rendait la main. Le questionnaire, lui, ne
peut pas se déclencher sans un VRAI appel d'outil : la reprise a besoin d'un
`tool_call_id` pour remplacer le `ToolMessage` par les réponses et replanifier
le nœud. Tant qu'aucun appel n'est émis, il n'y a rien à reprendre.

Faire dépendre un mécanisme déterministe d'une obéissance probabiliste, c'est
accepter que ça marche sur les bons modèles et échoue sur les autres — sans que
rien ne casse visiblement. Ici la condition est CALCULABLE : `missing()` rend
les champs absents. Ce que le code sait, le code le fait.

La nuance vaut d'être posée : il ne s'agit pas d'interdire au modèle de poser
des questions. Pour « je ne comprends pas ta demande », c'est à lui de décider —
la condition n'est pas calculable. La règle porte sur la CONDITION, pas sur la
clarification.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage

#: Le statut qui déclenche une demande. Un outil qui veut être servi par ce nœud
#: rend ce statut ET une liste `missing` — pas l'un sans l'autre.
STATUT = "CLARIFICATION_REQUIRED"

#: Champ manquant → la question posée. Explicite, et pas dérivée du nom du champ :
#: « bankroll » donnerait une phrase acceptable, le champ suivant probablement pas.
#: L'interface ajoute elle-même « Autre (préciser) », donc un montant libre reste
#: toujours possible — ne pas l'inscrire ici.
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
    """Les champs que ce résultat d'outil déclare manquants, s'il en déclare.

    Un champ sans question connue est ÉCARTÉ plutôt que posé maladroitement :
    mieux vaut laisser le modèle expliquer le manque que d'ouvrir un
    questionnaire dont l'intitulé serait un nom de variable.
    """
    charge = _charge(message)
    if not charge or charge.get("status") != STATUT:
        return ()
    manquants = charge.get("missing") or ()
    if not isinstance(manquants, (list, tuple)):
        return ()
    return tuple(c for c in manquants if c in QUESTIONS)


def deja_demande(messages: list, champs: tuple[str, ...]) -> bool:
    """A-t-on DÉJÀ posé ces questions sur ce fil ?

    Sans cette garde, un modèle qui rappellerait l'outil sans reporter la réponse
    relancerait le questionnaire indéfiniment. Un correctif qui boucle est pire
    que le défaut qu'il corrige : le défaut, lui, rendait la main.
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
    """Arête conditionnelle après le nœud d'outils.

    Quatre issues : enregistrer une réponse d'autorisation, poser une question de
    clarification, demander une autorisation, ou rendre la main au modèle.

    UN SEUL questionnaire en vol, tous genres confondus. Une demande qui arrive
    alors que le slot est pris repart vers le modèle — le tour se termine en
    disant que l'autorisation manque, et il réessaiera. Elle n'est ni mise en
    file, ni substituée à celle en cours : écraser une confirmation en attente
    la ferait disparaître sans que personne ait répondu.
    """
    from src.orchestrator import confirmation

    messages = state.get("messages") or []
    if not messages:
        return "chatbot"
    dernier = messages[-1]

    # 1. Une réponse d'autorisation prime : elle LIBÈRE le slot, donc la traiter
    #    en dernier bloquerait tout le reste.
    if confirmation.reponse_de_confirmation(dernier) is not None:
        return "enregistrer_autorisation"

    # 2. Une réponse de clarification rend le slot sans autre effet.
    en_cours = confirmation.en_vol()
    if (en_cours and en_cours["genre"] == "clarification"
            and getattr(dernier, "tool_call_id", None) == en_cours["tool_call_id"]):
        confirmation.liberer(en_cours["tool_call_id"])
        return "chatbot"

    if en_cours is not None:
        return "chatbot"          # slot occupé : refus, jamais écrasement

    champs = champs_manquants(dernier)
    if champs and not deja_demande(messages[:-1], champs):
        return "clarifier"

    if confirmation.commande_a_confirmer(dernier):
        return "confirmer"

    return "chatbot"


def clarifier(state: dict) -> dict:
    """Émet l'appel d'outil que le modèle aurait dû faire.

    Un `AIMessage` sans texte et porteur d'un `tool_call` : indiscernable, pour
    la suite du graphe, d'un appel que le modèle aurait décidé. Toute la
    machinerie de reprise — placeholder, `as_node`, `RemoveMessage` — fonctionne
    sans être touchée, ce qui est le point : ces chemins-là ont coûté cher à
    stabiliser et n'ont aucune raison d'être rouverts.
    """
    from src.orchestrator import confirmation

    champs = champs_manquants(state["messages"][-1])
    questions = [dict(QUESTIONS[c]) for c in champs]
    identifiant = f"clarif_{uuid4().hex[:16]}"
    # Le slot est partagé avec les confirmations : une question posée pendant
    # qu'une autorisation attend rendrait les deux illisibles.
    confirmation.reserver("clarification", ",".join(champs), identifiant)
    return {"messages": [AIMessage(
        content="",
        tool_calls=[{
            "name": "ask_clarification",
            "args": {"questions": questions},
            "id": identifiant,
        }],
    )]}
