"""Le nœud qui fait relire un brouillon de mail avant envoi.

`gmail_send_email` prépare un brouillon sans l'envoyer ; ce nœud le montre et,
sur accord, appelle `_do_send()`.

L'envoi a lieu APRÈS `demander()` : ce qui précède est rejoué (cf. `hitl`), et un
mail parti deux fois ne se rattrape pas.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from src.orchestrator.hitl import ENVOI, Demande, Question, demander

ENVOYER, ANNULER, MODIFIER = "Envoyer", "Annuler", "Modifier"

#: Une décision prise dans un questionnaire est une entrée de l'utilisateur :
#: elle arrive au modèle comme telle, jamais comme un `AIMessage` — que le TUI
#: afficherait et que le modèle relirait comme son propre tour.
def note_pour_le_modele(texte: str) -> HumanMessage:
    return HumanMessage(content=texte)


#: L'outil qui prépare le brouillon. Nommé ici pour qu'un renommage côté Gmail
#: casse à un seul endroit.
OUTIL_BROUILLON = "gmail_send_email"


def _brouillon() -> dict[str, Any] | None:
    """Le brouillon en attente, ou None."""
    try:
        from src.agents.gmail.tools import _draft
    except Exception:
        return None
    return dict(_draft) if _draft.get("has_draft") else None


def envoi_attendu(state: dict) -> bool:
    """Le dernier outil a préparé un brouillon qui attend un accord."""
    messages = state.get("messages") or []
    if not messages:
        return False
    dernier = messages[-1]
    if not isinstance(dernier, ToolMessage):
        return False
    if (getattr(dernier, "name", None) or "") != OUTIL_BROUILLON:
        return False
    return _brouillon() is not None


def _apercu(brouillon: dict[str, Any]) -> str:
    lignes = [f"À      : {brouillon.get('to') or ''}",
              f"Objet  : {brouillon.get('subject') or ''}"]
    for champ, etiquette in (("cc", "Copie"), ("bcc", "Copie cachée")):
        if brouillon.get(champ):
            lignes.append(f"{etiquette:6} : {brouillon[champ]}")
    corps = (brouillon.get("body") or "").strip()
    return "\n".join(lignes) + "\n\n" + corps


def envoyer(state: dict) -> dict:
    """Fait relire le brouillon, puis envoie ou abandonne selon la réponse."""
    brouillon = _brouillon()
    if brouillon is None:
        return {"messages": []}

    reponses = demander(Demande(
        genre=ENVOI,
        cle=f"{brouillon.get('to') or ''}|{brouillon.get('subject') or ''}",
        apercu=_apercu(brouillon),
        extra={c: brouillon.get(c) for c in ("to", "subject", "body", "cc", "bcc")},
        questions=(
            Question(texte="Envoyer ce mail ?",
                     choix=(ENVOYER, ANNULER, MODIFIER), affirmatif=ENVOYER),
            Question(texte="Que faut-il changer ?"),
        ),
    ))

    # ── Après l'interruption : exécuté une seule fois ───────────────────────
    decision = (reponses[0] or "").strip()
    precision = (reponses[1] or "").strip() if len(reponses) > 1 else ""

    if decision == ENVOYER:
        from src.agents.gmail.tools import _do_send
        return {"messages": [note_pour_le_modele(
            f"{_do_send()} Confirme-le brièvement à l'utilisateur.")]}

    _abandonner()
    if decision == MODIFIER and precision:
        # Dire ce qu'il faut FAIRE, pas seulement ce qui s'est passé. Sans cette
        # consigne, le modèle constate la demande et redemande quoi faire.
        return {"messages": [note_pour_le_modele(
            f"Le mail n'a pas été envoyé. {precision}. Prépare un nouveau "
            f"brouillon avec gmail_send_email en tenant compte de cette demande.")]}
    return {"messages": [note_pour_le_modele(
        "L'utilisateur a annulé l'envoi du mail. N'en prépare pas d'autre "
        "sans qu'il le demande ; dis-lui simplement que c'est annulé.")]}


def _abandonner() -> None:
    """Vide le brouillon.

    Sans quoi il resterait en attente et le nœud se redéclencherait au tour
    suivant sur un mail déjà refusé.
    """
    try:
        from src.agents.gmail.tools import _vider_brouillon
        _vider_brouillon()
    except Exception:
        pass
