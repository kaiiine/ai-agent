# src/agents/cron/tools.py

import json
from langchain_core.tools import tool
from src.agents.cron.store import add_task, get_tasks, deactivate_task
from src.agents.cron.surveillance import CONDITIONS, consigne


@tool("schedule_task")
def schedule_task(
    description: str,
    prompt: str,
    interval_sec: int,
    notify_channels: list[str],
    run_at: str="",
    stop_condition: str = "",
) -> str:
    """Planifie une tâche récurrente ou one-shot exécutée par le daemon Axon.
    
    description: libellé humain court ("Surveille score France-Espagne")
    prompt: ce que le daemon doit faire/vérifier à chaque exécution.
            Utilise {last_result} pour référencer l'état précédent.
    interval_seconds: fréquence en secondes (300 = toutes les 5 min)
    notify_channels: ["desktop"] ou ["desktop","slack"] ou ["slack"]
    run_at: datetime ISO pour one-shot (ex: "2026-07-21T18:00:00"). Vide = répétitif.
    stop_condition: condition d'arrêt auto ("si le match est terminé"). Optionnel.

    L'ENVOI EST AUTOMATIQUE : le daemon publie lui-même le résultat sur les
    `notify_channels` demandés. Pour Slack il poste dans le canal configuré côté serveur
    (variable SLACK_CRON_CHANNEL, défaut "test-cron") avec les identifiants déjà en place.
    Ne demande donc JAMAIS d'URL de webhook, de clé API d'envoi ni d'adresse e-mail :
    il suffit de mettre "slack" dans notify_channels.
    """
    taskId = add_task(
        description=description,
        prompt=prompt,
        interval_sec=interval_sec,
        notif_channels=notify_channels,
        run_at = run_at,
        stop_condition=stop_condition
    )
    mins = interval_sec // 60
    freq = f"toutes les {mins} min" if not run_at else f"à {run_at}"
    
    return json.dumps({
        "status": "scheduled",
        "id": taskId,
        "description": description,
        "frequency": freq,
        "channels": notify_channels,
    })

@tool("list_cron_tasks")
def list_cron_task(active: bool) -> str:
    """Liste toutes les tâches planifiées. L'argument active permet de lsiter lestâches qui sont actives (True) ou non (False)"""
    tasks = get_tasks(active_only=active)
    if not tasks:
        return "Aucune tâche planifiée active"
    return json.dumps(tasks, default=str)


@tool("stop_cron_task")
def stop_cron_task(taskId: str) -> str:
    """Désactive une tâche planifiée par son ID."""
    ok = deactivate_task(taskId)
    return f"Tâche {taskId} désactivée" if ok else f"ID introuvable: {taskId}"


@tool("surveiller")
def surveiller(
    description: str,
    quoi_relever: str,
    comment_relever: str,
    condition: str,
    interval_sec: int,
    notify_channels: list[str],
    seuil: float = 0.0,
) -> str:
    """Surveille une valeur dans le temps et prévient QUAND ELLE CHANGE.

    Utilise ce tool quand l'utilisateur veut :
    - être prévenu si un prix baisse, monte, ou passe sous un montant
    - savoir quand une page web change, quand une place se libère
    - garder un œil sur quelque chose, être tenu au courant d'une évolution
    - suivre une valeur et n'être alerté qu'en cas de mouvement

    Mots-clés : surveille, surveiller, veille, préviens-moi si, alerte-moi quand,
    tiens-moi au courant, garde un œil, suis l'évolution, baisse, monte, change

    Différence avec schedule_task : une tâche planifiée rapporte À CHAQUE
    passage ; une veille ne rapporte QUE si la valeur a bougé. Pour surveiller un
    prix toutes les heures, c'est ce tool — sinon l'utilisateur reçoit vingt-quatre
    notifications identiques par jour.

    Args:
        description: libellé court ("Prix du Legion 7i")
        quoi_relever: la valeur suivie, en clair ("le prix en euros")
        comment_relever: comment l'obtenir ("consulte <url> et lis le prix affiché")
        condition: "change" | "baisse" | "hausse" | "sous" | "sur"
        interval_sec: fréquence en secondes (3600 = toutes les heures)
        notify_channels: ["desktop"] et/ou ["slack"]
        seuil: le montant, pour "sous" et "sur" uniquement
    Returns:
        {"status": "surveille", "id": ..., ...}
    """
    if condition not in CONDITIONS:
        return json.dumps({
            "status": "error",
            "error": f"condition inconnue : {condition}. Attendu : {', '.join(CONDITIONS)}",
        })
    if condition in ("sous", "sur") and not seuil:
        return json.dumps({
            "status": "error",
            "error": f"la condition « {condition} » exige un seuil non nul.",
        })

    taskId = add_task(
        description=description,
        prompt=comment_relever + consigne(quoi_relever),
        interval_sec=interval_sec,
        notif_channels=notify_channels,
        surveillance={
            "quoi": quoi_relever,
            "condition": condition,
            "seuil": seuil if condition in ("sous", "sur") else None,
            "derniere": None,
        },
    )
    return json.dumps({
        "status": "surveille",
        "id": taskId,
        "description": description,
        "condition": condition,
        "seuil": seuil if condition in ("sous", "sur") else None,
        "frequency": f"toutes les {max(1, interval_sec // 60)} min",
        "channels": notify_channels,
        "note": ("Le premier passage établit la référence sans alerter — c'est "
                 "normal, il n'y a rien à comparer."),
    })
