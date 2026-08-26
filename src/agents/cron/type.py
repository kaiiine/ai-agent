"""Cron type"""

from __future__ import annotations
from typing import Any, NotRequired, TypedDict, Literal


NotifyChannel = Literal["desktop", "slack"]

class CronTask(TypedDict):
    id: str
    description: str
    prompt: str
    interval_sec: int
    notify_channels:list[NotifyChannel]
    run_at: str | None
    stop_condition: str 
    created_at: str
    last_run: str | None
    last_result: str | None
    active: bool
    #: Commandes shell permises à l'identique, écrites par l'utilisateur — jamais
    #: par le modèle. Absente, la tâche ne lance que ce qui est reconnu sûr.
    commandes_autorisees: NotRequired[list[str]]
    #: Présent si la tâche est une veille : cf. `cron/surveillance.py`.
    surveillance: NotRequired[dict[str, Any]]
    