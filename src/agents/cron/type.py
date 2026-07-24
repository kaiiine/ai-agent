"""Cron type"""

from __future__ import annotations
from typing import TypedDict, Literal


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
    