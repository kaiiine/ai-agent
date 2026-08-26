"""Le nœud qui fait relire les fichiers et cellules proposés avant écriture.

Se déclenche quand `pending_changes` ou `pending_cell_changes` contient quelque
chose et que le mode d'édition n'est pas `auto`. L'écriture a lieu APRÈS
`demander()` : ce qui précède est rejoué (cf. `hitl`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from src.orchestrator.hitl import DIFF, Demande, Question, demander

APPLIQUER, REFUSER, PRECISER = "Appliquer", "Refuser", "Préciser"

#: Une décision prise dans un questionnaire est une entrée de l'utilisateur :
#: elle arrive au modèle comme telle, jamais comme un `AIMessage` — que le TUI
#: afficherait et que le modèle relirait comme son propre tour.
def note_pour_le_modele(texte: str) -> HumanMessage:
    return HumanMessage(content=texte)



def _fichiers() -> list:
    from src.agents.coding.pending import pending_changes

    return list(pending_changes.items)


def _cellules() -> list:
    """Les cellules de notebook en attente de revue."""
    try:
        from src.agents.notebook.tools import pending_cell_changes
    except Exception:
        return []
    return list(pending_cell_changes.items)


def _en_attente() -> list:
    return _fichiers() + _cellules()


def revision_attendue(state: dict | None = None) -> bool:
    """Quelque chose attend une revue, et le mode n'est pas `auto`."""
    if not _en_attente():
        return False
    try:
        from src.ui.edit_mode import get_mode
    except Exception:
        return True
    try:
        return get_mode() != "auto"
    except Exception:
        return True


def _decrire(changement) -> str:
    """Une ligne de résumé pour un changement, fichier ou cellule."""
    nom = Path(changement.path).name
    if hasattr(changement, "cell_index"):
        place = ("nouvelle cellule" if changement.cell_index < 0
                 else f"cellule {changement.cell_index}")
        return f"  {nom}  ({place})  —  {changement.description}"
    etat = "nouveau" if not changement.original else "modifié"
    return f"  {nom}  ({etat})  —  {changement.description}"


def _apercu(changements: list) -> str:
    """Résumé texte, pour les clients sans rendu de diff.

    Le TUI l'ignore : il reçoit les changements complets dans `Demande.extra`.
    """
    return "\n".join(_decrire(c) for c in changements)


def reviser(state: dict) -> dict:
    """Fait relire ce qui est proposé, puis applique la décision."""
    from src.agents.coding.pending import pending_changes

    fichiers, cellules = _fichiers(), _cellules()
    changements = fichiers + cellules
    if not changements:
        return {"messages": []}

    nombre = len(changements)
    reponses = demander(Demande(
        genre=DIFF,
        cle=",".join(c.path for c in changements),
        apercu=_apercu(changements),
        extra={
            "changements": [
                {"path": c.path, "original": c.original,
                 "proposed": c.proposed, "description": c.description}
                for c in fichiers],
            "cellules": [
                {"path": c.path, "cell_index": c.cell_index,
                 "insert_after": c.insert_after, "cell_type": c.cell_type,
                 "original_source": c.original_source,
                 "proposed_source": c.proposed_source,
                 "description": c.description}
                for c in cellules],
        },
        questions=(
            Question(
                texte=f"{nombre} modification{'s' if nombre > 1 else ''} proposée"
                      f"{'s' if nombre > 1 else ''} — que faire ?",
                choix=(APPLIQUER, REFUSER, PRECISER),
                affirmatif=APPLIQUER),
            Question(texte="Que faut-il ajuster ?"),
        ),
    ))

    # ── Après l'interruption : exécuté une seule fois ───────────────────────
    decision = (reponses[0] or "").strip()
    precision = (reponses[1] or "").strip() if len(reponses) > 1 else ""

    if decision == APPLIQUER:
        appliques, erreurs = appliquer(pending_changes.pop_all())
        a2, e2 = appliquer_cellules(_prendre_cellules())
        return {"messages": [note_pour_le_modele(
            _compte_rendu(appliques + a2, erreurs + e2)
            + " Poursuis la tâche ; n'écris pas ces fichiers une seconde fois.")]}

    pending_changes.clear()
    _prendre_cellules()
    if decision == PRECISER and precision:
        return {"messages": [note_pour_le_modele(
            f"Les modifications n'ont pas été appliquées. {precision}. Propose "
            f"une nouvelle version qui en tient compte.")]}
    return {"messages": [note_pour_le_modele(
        "L'utilisateur a refusé les modifications proposées. Ne les repropose "
        "pas à l'identique ; demande-lui ce qui n'allait pas si tu ne le sais pas.")]}


def appliquer(changements: list) -> tuple[list[str], list[str]]:
    """Écrit les fichiers. Rend (chemins écrits, erreurs).

    Un échec sur un fichier n'interrompt pas les suivants.
    """
    appliques: list[str] = []
    erreurs: list[str] = []
    for changement in changements:
        try:
            chemin = Path(changement.path)
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(changement.proposed, encoding="utf-8")
            appliques.append(changement.path)
        except Exception as erreur:      # noqa: BLE001 — rapporté, jamais avalé
            erreurs.append(f"{changement.path} : {erreur}")
    return appliques, erreurs


def _compte_rendu(appliques: list[str], erreurs: list[str]) -> str:
    morceaux = []
    if appliques:
        morceaux.append(f"{len(appliques)} fichier(s) écrit(s) : "
                        + ", ".join(Path(p).name for p in appliques))
    if erreurs:
        morceaux.append("Échecs : " + " ; ".join(erreurs))
    return " — ".join(morceaux) or "Aucun fichier écrit."


def _prendre_cellules() -> list:
    try:
        from src.agents.notebook.tools import pending_cell_changes
    except Exception:
        return []
    return pending_cell_changes.pop_all()


def appliquer_cellules(cellules: list) -> tuple[list[str], list[str]]:
    """Écrit les cellules. Même contrat que `appliquer`."""
    appliques: list[str] = []
    erreurs: list[str] = []
    for cellule in cellules:
        try:
            from src.agents.notebook.tools import apply_cell_change
            apply_cell_change(cellule)
            appliques.append(f"{Path(cellule.path).name}#{cellule.cell_index}")
        except Exception as erreur:      # noqa: BLE001 — rapporté, jamais avalé
            erreurs.append(f"{cellule.path} : {erreur}")
    return appliques, erreurs
