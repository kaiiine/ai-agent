# src/agents/cron/tools.py

import json
from langchain_core.tools import tool
from src.agents.cron.store import add_task, get_tasks, deactivate_task


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
