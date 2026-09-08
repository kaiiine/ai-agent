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

    from src.agents.coding.noeud import tache_a_coder

    if tache_a_coder(dernier):
        return "coder"

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


def appel_clarification(message: Any) -> dict | None:
    """Le PREMIER appel à `ask_clarification` porté par ce message."""
    appels = appels_clarification(message)
    return appels[0] if appels else None


def appels_clarification(message: Any) -> list[dict]:
    """TOUS les appels à `ask_clarification` du message.

    Le modèle en émet parfois plusieurs d'un même souffle — un par question.
    Vécu sur « y a-t-il de bons paris à faire » : trois appels, un seul
    questionnaire affiché, et les deux autres restaient sans `ToolMessage`.
    `appels_en_attente` les voyait donc toujours en attente, le graphe revenait
    au nœud, `messages[-1]` était alors le `ToolMessage` du premier — donc plus
    aucun appel à traiter — et le tour se bloquait. Le modèle finissait par
    reposer ses questions en texte libre.
    """
    if not isinstance(message, AIMessage):
        return []
    return [a for a in getattr(message, "tool_calls", None) or []
            if a.get("name") == "ask_clarification"]


def _questions(appel: dict) -> tuple[Question, ...]:
    posees: list[Question] = []
    for brut in (appel.get("args") or {}).get("questions") or []:
        if isinstance(brut, str):
            texte, choix = brut.strip(), ()
        elif isinstance(brut, dict):
            texte = str(brut.get("question") or "").strip()
            choix = tuple(str(c) for c in (brut.get("choices") or ()))
        else:
            continue
        if texte:
            posees.append(Question(texte=texte, choix=choix))
    return tuple(posees)


def clarifier_appel(state: dict) -> dict:
    """Pose les questions que le modèle a demandées, avant que l'outil ne tourne.

    `ask_clarification` est un outil ordinaire : il rend ses propres questions au
    modèle en JSON, et rien ne les affiche. Le modèle les recevait comme une
    donnée, n'avait aucune raison de croire qu'elles avaient été posées, et
    rappelait l'outil — six fois sur un simple « coucou ». Les deux gardes
    anti-boucle cherchaient une clé `answers` que ce chemin ne produit jamais.
    """
    messages = state.get("messages") or []
    # Le porteur est le dernier AIMessage à outils, pas `messages[-1]` : quand un
    # appel du lot a déjà sa réponse, le dernier message est un `ToolMessage` et
    # le nœud ne trouvait plus rien à faire.
    porteur = next((m for m in reversed(messages)
                    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)), None)
    repondus = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    appels = [a for a in appels_clarification(porteur)
              if a.get("id", "clarification") not in repondus]
    if not appels:
        return {}

    identifiant = appels[0].get("id", "clarification")
    # Les questions des appels FUSIONNENT : l'utilisateur répond à un
    # questionnaire, pas à trois d'affilée. Chaque appel reçoit ensuite sa propre
    # réponse — un fournisseur refuse un tour dont les paires sont déséquilibrées.
    posees = tuple(q for a in appels for q in _questions(a))

    # Demander une information, ce n'est pas demander la permission. AXON garde
    # lui-même ce qui engage : la question en double n'ouvrait aucune porte.
    # Le statut n'est PAS `error` — le journal peint en rouge tout résultat
    # d'erreur, et l'utilisateur voyait « Question refusée » deux fois pour un
    # seul geste. Ce que le modèle ne devrait pas demander se règle dans son
    # prompt ; ici on laisse simplement passer.
    from src.agents.clarify.permission import SANS_OBJET, demande_une_permission

    def _repondre_a_tous(charge: str) -> dict:
        return {"messages": [
            ToolMessage(content=charge, tool_call_id=a.get("id", "clarification"),
                        name="ask_clarification")
            for a in appels
        ]}

    if posees and any(demande_une_permission(q.choix) for q in posees):
        return _repondre_a_tous(json.dumps({"status": "ok", "message": SANS_OBJET},
                                           ensure_ascii=False))

    if not posees:
        return _repondre_a_tous(json.dumps(
            {"status": "error", "error": "Aucune question exploitable — reformule."}))

    reponses = demander(Demande(genre=CLARIFICATION, cle=identifiant, questions=posees))

    # ── À partir d'ici : une seule fois ─────────────────────────────────────
    echange = {q.texte: r for q, r in zip(posees, reponses)}
    charge = json.dumps({"answers": echange}, ensure_ascii=False)
    return {"messages": [
        ToolMessage(content=charge, tool_call_id=a.get("id", "clarification"),
                    name="ask_clarification")
        for a in appels
    ]}


def appels_en_attente(state: dict) -> bool:
    """Reste-t-il, dans le dernier lot, un appel sans réponse ?

    Le modèle peut demander l'heure ET une clarification d'un même souffle.
    Router tout le lot vers la question laissait l'autre appel sans résultat, et
    un fournisseur refuse un tour dont les paires sont déséquilibrées.
    """
    messages = state.get("messages") or []
    porteur = next((m for m in reversed(messages)
                    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)), None)
    if porteur is None:
        return False
    repondus = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    return any(a["id"] not in repondus for a in porteur.tool_calls)
