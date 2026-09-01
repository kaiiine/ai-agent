"""Le nœud qui demande l'accord d'exécuter une commande shell.

`shell_run` rend `requires_confirmation` ; ce nœud pose la question et, sur
accord, inscrit l'autorisation puis réémet l'appel.

L'accord est inscrit APRÈS `demander()` : ce qui précède est rejoué (cf. `hitl`).
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.shell.autorisation import accorder
from src.orchestrator.hitl import (
    AUTORISATION,
    Demande,
    Question,
    accorde,
    demander,
)

#: Libellés affichés. Lequel vaut accord est déclaré sur la `Question`.
OUI, NON = "Oui, exécuter", "Non, annuler"

#: Une décision prise dans un questionnaire est une entrée de l'utilisateur :
#: elle arrive au modèle comme telle, jamais comme un `AIMessage` — que le TUI
#: afficherait et que le modèle relirait comme son propre tour.
def note_pour_le_modele(texte: str) -> HumanMessage:
    from src.orchestrator.note_interne import note

    return note(texte)


# ── Lecture des messages ─────────────────────────────────────────────────────
def _charge(message: Any) -> dict | None:
    if not isinstance(message, ToolMessage) or not isinstance(message.content, str):
        return None
    try:
        charge = json.loads(message.content)
    except (ValueError, TypeError):
        return None
    return charge if isinstance(charge, dict) else None


def commande_a_confirmer(message: Any) -> str | None:
    """La commande dont ce résultat d'outil réclame l'autorisation, ou None."""
    charge = _charge(message)
    if not charge or charge.get("status") != "requires_confirmation":
        return None
    commande = charge.get("command")
    return commande if isinstance(commande, str) and commande.strip() else None


def _libelle(charge: dict, commande: str) -> str:
    """L'intitulé de la question : le motif, la commande, et OÙ elle s'exécute.

    Le répertoire manquait. « rm -rf ./* » ne dit pas ce que `./` désigne, et on
    ne peut pas accorder ce qu'on ne voit pas : le même écran vaut pour un
    dossier d'essai et pour la racine d'un projet. Il n'est montré que si la
    commande porte un chemin RELATIF — sur « rm -rf /tmp/x », le répertoire
    n'apprend rien et allongerait la question pour rien.

    L'aperçu d'écriture voyage à part, dans `Demande.apercu`.
    """
    motif = charge.get("reason")
    entete = {"destructive": "Commande DESTRUCTIVE",
              "inconnue": "Commande non reconnue comme sûre"}.get(motif, "Commande")
    if charge.get("host"):
        entete = f"Écriture sur {charge['host']} (machine DISTANTE)"
    lieu = charge.get("cwd") or ""
    if lieu and _porte_un_chemin_relatif(commande):
        return f"{entete} :\n\n{commande}\n\ndans  {lieu}"
    return f"{entete} :\n\n{commande}"


#: Un argument qui n'est ni une option ni un chemin absolu : ce que la commande
#: touche dépend alors du répertoire courant.
_ABSOLU = ("/", "~")


def _porte_un_chemin_relatif(commande: str) -> bool:
    for mot in commande.split()[1:]:
        if mot.startswith("-") or not mot:
            continue
        if not mot.startswith(_ABSOLU):
            return True
    return False


# ── Le nœud ──────────────────────────────────────────────────────────────────
def confirmer(state: dict) -> dict:
    """Demande l'accord, puis inscrit l'autorisation et réémet l'appel."""
    dernier = state["messages"][-1]
    charge = _charge(dernier) or {}
    commande = commande_a_confirmer(dernier) or ""

    reponses = demander(Demande(
        genre=AUTORISATION,
        cle=commande,
        apercu=charge.get("preview") or "",
        extra={k: charge[k] for k in ("host", "target", "reason") if k in charge},
        questions=(Question(_libelle(charge, commande),
                            choix=(NON, OUI), affirmatif=OUI),),
    ))

    # ── Après l'interruption : exécuté une seule fois ───────────────────────
    if not accorde(reponses[0], Question(_libelle(charge, commande),
                                         choix=(NON, OUI), affirmatif=OUI)):
        return {"messages": [note_pour_le_modele(
            f"L'utilisateur a refusé d'exécuter : {commande}. Ne la relance pas ; "
            f"propose autre chose ou demande-lui ce qu'il préfère.")]}

    accorder(commande)
    # Réémettre l'appel : sans cela, l'accord serait donné et rien ne partirait.
    return {"messages": [AIMessage(
        content="",
        tool_calls=[{"name": "shell_run", "args": {"command": commande},
                     "id": f"apres_accord_{uuid4().hex[:12]}"}],
    )]}


def apres_confirmation(state: dict) -> str:
    """« tools » si l'appel a été réémis, « chatbot » sinon."""
    dernier = (state.get("messages") or [None])[-1]
    return "tools" if getattr(dernier, "tool_calls", None) else "chatbot"
