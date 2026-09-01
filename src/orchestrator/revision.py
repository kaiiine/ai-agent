"""Le nœud qui fait relire les fichiers et cellules proposés avant écriture.

Se déclenche quand `pending_changes` ou `pending_cell_changes` contient quelque
chose et que le mode d'édition n'est pas `auto`. L'écriture a lieu APRÈS
`demander()` : ce qui précède est rejoué (cf. `hitl`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import json

from langchain_core.messages import HumanMessage, ToolMessage

from src.orchestrator.hitl import DIFF, Demande, Question, demander
from src.orchestrator.verification import consigne, verifier

APPLIQUER, REFUSER, PRECISER = "Appliquer", "Refuser", "Préciser"

#: Une décision prise dans un questionnaire est une entrée de l'utilisateur :
#: elle arrive au modèle comme telle, jamais comme un `AIMessage` — que le TUI
#: afficherait et que le modèle relirait comme son propre tour.
def note_pour_le_modele(texte: str) -> HumanMessage:
    from src.orchestrator.note_interne import note

    return note(texte)


def rappel_du_plan(chemins: list[str]) -> str:
    """Nomme l'étape en cours qui mentionne un fichier qu'on vient d'écrire.

    On ne la coche PAS. Écrire un fichier n'achève pas forcément une étape : elle
    peut en demander plusieurs, ou plusieurs passes sur le même, ou une écriture
    ET un test. Seul le modèle sait où il en est — mais il n'appelle presque
    jamais `dev_plan_step_done`, et une étape qui reste ouverte fait croire à du
    travail en cours.

    Le rappel met donc la question là où est la réponse, au lieu de trancher à
    l'aveugle. Vécu : « Créer le fichier tri.py » est restée en cours alors que le
    fichier était écrit, relu et exécuté avec succès.
    """
    from src.agents.coding.pending import dev_plan

    if not dev_plan.steps:
        return ""
    noms = {Path(chemin).name for chemin in chemins}
    concernees = [(i, e) for i, e in enumerate(dev_plan.steps)
                  if not e.done and any(nom in e.label for nom in noms)]
    if not concernees:
        return ""
    detail = " ; ".join(f"étape {i + 1} « {e.label[:60]} »" for i, e in concernees)
    return (f" Le plan a encore en cours : {detail}. Si ce qui vient d'être écrit "
            f"l'achève, appelle `dev_plan_step_done` — sinon poursuis, il reste du "
            f"travail dessus.")


#: Ce que le résultat doit raconter une fois la revue faite.
_RECITS = {
    "applied": "Fichier écrit sur le disque. N'y reviens pas.",
    "rejected": "L'utilisateur a refusé. Ne repropose pas la même chose.",
}

#: Les outils dont le résultat annonce une proposition, pas un fait accompli.
_OUTILS_PROPOSANTS = ("propose_file_change", "propose_file_delete", "edit_file",
                      "notebook_edit_cell", "notebook_insert_cell")


def _corriger_les_resultats(messages: list, verdict: str) -> list[ToolMessage]:
    """Réécrit les résultats d'outils restés sur « awaiting_confirmation ».

    Un outil de proposition rend `{"status": "proposed", "awaiting_confirmation":
    true}`, et rien ne le met à jour après la revue. Le modèle lisait donc DEUX
    affirmations contradictoires : son propre outil disant « en attente », et une
    note humaine disant « écrit ». Il croit son outil — vécu, il reproposait le
    même fichier une seconde fois, avec un diff vide.

    `add_messages` remplace un message de même `id` : on réécrit sur place au lieu
    d'empiler une correction de plus.
    """
    corriges: list[ToolMessage] = []
    for message in messages:
        if not isinstance(message, ToolMessage) or not message.id:
            continue
        if getattr(message, "name", None) not in _OUTILS_PROPOSANTS:
            continue
        contenu = message.content if isinstance(message.content, str) else ""
        if "awaiting_confirmation" not in contenu:
            continue
        try:
            charge = json.loads(contenu)
        except (ValueError, TypeError):
            continue
        charge.pop("awaiting_confirmation", None)
        charge["status"] = verdict
        # Le RÉCIT aussi, pas seulement le statut. `_coding_progress` y écrit
        # « Proposition enregistrée. L'utilisateur la relira avant écriture » —
        # laissé tel quel, l'objet disait à la fois « appliqué » et « on va te la
        # relire », et le modèle reproposait le même fichier, parfois à vide.
        charge["message"] = _RECITS.get(verdict, verdict)
        corriges.append(ToolMessage(content=json.dumps(charge, ensure_ascii=False),
                                    tool_call_id=message.tool_call_id,
                                    name=message.name, id=message.id))
    return corriges



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
    if getattr(changement, "supprime", False):
        return f"  {nom}  (supprimé)  —  {changement.description}"
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

    messages = state.get("messages") or []
    if decision == APPLIQUER:
        # Deux piles distinctes : les fichiers, et les cellules de notebook. Un
        # `.ipynb` ne s'écrit pas comme un fichier texte — le modifier entier
        # perdrait les sorties et les métadonnées des autres cellules.
        fichiers_ecrits, echecs = appliquer(pending_changes.pop_all())
        cellules_ecrites, echecs_cellules = appliquer_cellules(_prendre_cellules())
        ecrits = fichiers_ecrits + cellules_ecrites

        rendu = _compte_rendu(ecrits, echecs + echecs_cellules)

        # Écrit n'est pas debout. Contrôle déterministe, sans appel de modèle : on
        # demande au langage si le fichier parse. Vécu — une réécriture a rendu un
        # source dont tout le corps tenait sur une ligne avec des `\n` littéraux ;
        # le diff s'affichait, le script était mort.
        fautifs = verifier(ecrits)
        if fautifs:
            return {"messages": _corriger_les_resultats(messages, "applied")
                    + [note_pour_le_modele(f"{rendu} {consigne(fautifs)}")]}

        # Un FAIT, pas un interdit. « N'écris pas ces fichiers une seconde fois »
        # visait la reproposition à vide — laquelle est déjà refusée par
        # `propose_file_change`, qui rejette un contenu identique à celui du
        # disque. Interdire ici aurait bloqué toute suite légitime : une étape
        # suivante du plan, une correction, un ajout demandé après coup.
        return {"messages": _corriger_les_resultats(messages, "applied")
                + [note_pour_le_modele(
                    f"{rendu} Ils sont sur le disque : relis-les plutôt que de les "
                    f"réécrire de mémoire, et poursuis la tâche."
                    + rappel_du_plan(ecrits))]}

    pending_changes.clear()
    _prendre_cellules()
    if decision == PRECISER and precision:
        return {"messages": _corriger_les_resultats(messages, "rejected")
                + [note_pour_le_modele(
                    f"Les modifications n'ont pas été appliquées — RIEN n'a été écrit "
                    f"sur le disque, et c'est normal à ce stade. {precision}. Repropose "
                    f"le fichier ENTIER avec cette correction, directement : ne "
                    f"replanifie pas, ne revérifie pas le disque, ne recommence pas "
                    f"l'analyse. Tu as déjà le contenu.")]}
    return {"messages": _corriger_les_resultats(messages, "rejected")
            + [note_pour_le_modele(
                "L'utilisateur a refusé les modifications proposées. Ne les repropose "
                "pas à l'identique ; demande-lui ce qui n'allait pas si tu ne le sais pas.")]}


def appliquer(changements: list) -> tuple[list[str], list[str]]:
    """Écrit — ou efface. Rend (chemins traités, erreurs).

    Un échec sur un fichier n'interrompt pas les suivants.

    Le corps était recopié ici : un `write_text(proposed)` qui ignorait
    `supprime`. Une suppression relue puis acceptée CRÉAIT donc un fichier vide
    au lieu d'effacer — vécu, `fragments-???.txt` 0B ; le modèle le voyait
    revenir, reproposait la suppression, et le fichier renaissait à chaque tour.
    `pending.appliquer` sait effacer, garde de quoi défaire, et note le fait pour
    les preuves du plan : on l'appelle au lieu de le redire à moitié.
    """
    from src.agents.coding.pending import appliquer as ecrire_ou_effacer

    appliques: list[str] = []
    erreurs: list[str] = []
    for changement in changements:
        try:
            ecrire_ou_effacer(changement)
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
            from src.agents.coding.pending import recent_tools
            from src.agents.notebook.tools import apply_cell_change
            apply_cell_change(cellule)
            recent_tools.note_cellule(cellule.path, cellule.cell_index)
            appliques.append(f"{Path(cellule.path).name}#{cellule.cell_index}")
        except Exception as erreur:      # noqa: BLE001 — rapporté, jamais avalé
            erreurs.append(f"{cellule.path} : {erreur}")
    return appliques, erreurs
