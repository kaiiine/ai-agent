"""Lancer une tâche planifiée maintenant, sans notifier ni rien enregistrer."""
from __future__ import annotations

from src.agents.cron.store import get_tasks


def essayer(task_id: str) -> dict:
    # Passe par `_run_task` plutôt que de réimplémenter : un essai qui
    # contournerait les autorisations dirait « ça marche » d'une tâche qui serait
    # bloquée en production.
    from src.cron_daemon import _run_task

    tache = next((t for t in get_tasks() if t["id"] == task_id), None)
    if tache is None:
        return {"status": "introuvable", "id": task_id}

    journal = _run_task(task_id, essai=True) or {}
    return {
        "status": "essai",
        "id": task_id,
        "description": tache.get("description", ""),
        "active": tache.get("active", False),
        "resultat": journal.get("result_summary", ""),
        "erreur": journal.get("error"),
        "aurait_notifie": journal.get("aurait_notifie"),
        "surveillance": journal.get("surveillance"),
        "duree_ms": journal.get("duration_ms"),
    }


def rendre(essai: dict) -> str:
    if essai.get("status") == "introuvable":
        return f"Aucune tâche {essai['id']}."

    actif = "oui" if essai["active"] else "NON — elle ne tournera pas"
    lignes = [f"Essai de « {essai['description']} » ({essai['id']})",
              f"  active      : {actif}",
              f"  durée       : {essai.get('duree_ms', 0)} ms"]

    if essai.get("erreur"):
        lignes.append(f"  ÉCHEC       : {essai['erreur']}")

    veille = essai.get("surveillance")
    if veille:
        lignes += [f"  valeur      : {veille.get('valeur')}",
                   f"  verdict     : {veille.get('raison')}"]

    notif = essai.get("aurait_notifie")
    if notif:
        lignes += [f"  AURAIT PRÉVENU sur {', '.join(notif.get('canaux') or [])} :",
                   f"    {notif.get('message', '')}"]
    elif not essai.get("erreur"):
        lignes.append("  n'aurait rien envoyé")

    if essai.get("resultat"):
        lignes.append(f"  résumé      : {essai['resultat'][:200]}")
    return "\n".join(lignes)
