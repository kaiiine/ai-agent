"""Cron type"""

from __future__ import annotations
from typing import NotRequired, TypedDict, Literal


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
    #: Commandes shell que CETTE tâche a le droit de lancer sans confirmation,
    #: à l'identique. Écrite par l'utilisateur, jamais par le modèle : c'est ce
    #: qui la distingue d'une autorisation que l'agent s'accorderait lui-même.
    #:
    #: Absente ou vide, la tâche ne peut lancer que des commandes reconnues sûres.
    #: C'est le défaut, et il est volontaire : une commande destructive lancée
    #: sans personne devant l'écran est précisément le cas où l'on veut une
    #: barrière, pas une exemption.
    commandes_autorisees: NotRequired[list[str]]
    