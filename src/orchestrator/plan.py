"""Le nœud qui fait valider un plan avant de l'exécuter.

Dernier producteur de HITL à passer par `hitl`. Il diffère des autres : il se
déclenche sur le TEXTE du modèle — un bloc `<axon:plan>` — et non sur un appel
d'outil. Il s'intercale donc entre `chatbot` et la fin du tour.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.orchestrator.hitl import PLAN, Demande, Question, demander

OUVERT, FERME = "<axon:plan>", "</axon:plan>"
EXECUTER, PRECISER, ABANDONNER = "Exécuter le plan", "Préciser", "Abandonner"


def note_pour_le_modele(texte: str) -> HumanMessage:
    return HumanMessage(content=texte)


def _plan_du_message(message: Any) -> str | None:
    contenu = getattr(message, "content", None)
    if not isinstance(contenu, str) or OUVERT not in contenu or FERME not in contenu:
        return None
    return contenu.split(OUVERT, 1)[1].split(FERME, 1)[0].strip() or None


def plan_a_valider(state: dict) -> bool:
    """Le modèle vient de proposer un plan, et le mode plan est actif."""
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage):
        return False
    if getattr(messages[-1], "tool_calls", None):
        return False
    if _plan_du_message(messages[-1]) is None:
        return False
    try:
        from src.ui.plan_mode import is_active
        return is_active()
    except Exception:
        return False


def valider(state: dict) -> dict:
    """Fait valider le plan, puis inscrit la décision."""
    plan = _plan_du_message(state["messages"][-1]) or ""

    reponses = demander(Demande(
        genre=PLAN,
        cle=plan[:80],
        apercu=plan,
        questions=(
            Question(texte="Ce plan te convient ?",
                     choix=(ABANDONNER, PRECISER, EXECUTER), affirmatif=EXECUTER),
            Question(texte="Que faut-il changer ?"),
        ),
    ))

    # ── Après l'interruption : exécuté une seule fois ───────────────────────
    decision = (reponses[0] or "").strip()
    precision = (reponses[1] or "").strip() if len(reponses) > 1 else ""

    if decision == EXECUTER:
        _quitter_le_mode_plan()
        return {"messages": [note_pour_le_modele(
            "Plan approuvé. Exécute-le maintenant, en suivant exactement les "
            "étapes annoncées.")]}

    if decision == PRECISER and precision:
        # Le mode plan RESTE actif : on veut un plan révisé, pas une exécution.
        return {"messages": [note_pour_le_modele(
            f"Le plan n'est pas validé. {precision}. Propose un plan révisé qui "
            f"en tient compte.")]}

    _quitter_le_mode_plan()
    return {"messages": [note_pour_le_modele(
        "L'utilisateur a abandonné ce plan. N'exécute rien ; demande-lui ce "
        "qu'il préfère faire.")]}


def _quitter_le_mode_plan() -> None:
    try:
        from src.ui.plan_mode import set_active
        set_active(False)
    except Exception:
        pass
