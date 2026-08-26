"""Cron : To schedule cron jobs"""

from __future__ import annotations
import json
import uuid
from datetime import datetime
from pathlib import Path
from filelock import FileLock
from .type import CronTask

CRON_FILE = Path.home() / ".axon" / "crons.json"
LOG_DIR = Path.home() / ".axon" / "cron_logs"
_LOCK = FileLock(str(CRON_FILE) + ".lock")

def _load() -> list[CronTask]:
    CRON_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not CRON_FILE.exists():
        return []
    try:
        return json.loads(CRON_FILE.read_text())
    except Exception:
        return []

def _save(tasks: list[CronTask]) -> bool :
    try:
        CRON_FILE.parent.mkdir(parents=True, exist_ok=True)
        CRON_FILE.write_text(json.dumps(tasks, indent=2, default=str))
        return 1
    except Exception:
        raise ValueError("[CRON] Error saving the cron job")

def add_task(
        description: str,
        prompt: str,
        interval_sec: int,
        notif_channels: list[str],
        run_at: str="",
        stop_condition: str="",
        surveillance: dict | None = None,
) -> str:

    taskId = "cron_" + uuid.uuid4().hex[:8]
    try:
        task = CronTask(
            id = taskId,
            description = description,
            prompt = prompt,
            interval_sec = interval_sec,
            notify_channels = notif_channels,
            run_at = run_at,
            stop_condition = stop_condition,
            created_at = datetime.now().isoformat(),
            last_run = None,
            last_result = None,
            active = True
        )
        if surveillance is not None:
            task["surveillance"] = surveillance

        with _LOCK:
            tasks = _load()
            tasks.append(task)
            _save(tasks)

        return taskId
    except Exception:
        raise ValueError("[Cron]: Error creating the cron job")


def get_tasks(active_only: bool = False) -> list[CronTask]:
    tasks = _load()
    if active_only:
        return [t for t in tasks if t.get("active", False)]
    return tasks

def update_task(taskId: str, **fields) -> None:
    allowed_fields = {
        "description",
        "prompt",
        "interval_sec",
        "notify_channels",
        "run_at",
        "stop_condition",
        "last_run",
        "last_result",
        "active",
        # La veille met à jour sa dernière valeur relevée à chaque passage.
        "surveillance",
    }

    unknown_fields = fields.keys() - allowed_fields
    if unknown_fields:
        return 0

    try:
        with _LOCK:
            tasks = _load()
            for t in tasks:
                if t["id"] == taskId:
                    t.update(fields)
            _save(tasks)
    except Exception:
        raise ValueError("[CRON] Error updating the cron job")
    

def deactivate_task(taskId: str) -> int:
    try:
        with _LOCK:
            tasks = _load()
            for t in tasks:
                if t["id"] == taskId:
                    t["active"] = False
                    _save(tasks)
                    return 1
        return 0
    except Exception:
        raise ValueError("[CRON] Error desactivating the cron job")



# _____MONITORING______________________________________________

def append_log(taskId: str, entry: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{taskId}.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")

def get_logs(taskId: str, nb: int = 10) -> list[dict]:
    log_file = LOG_DIR / f"{taskId}.jsonl"
    if not log_file.exists():
        raise ValueError("[CRON MONITORING] File doesn't exist")
    lines = log_file.read_text().strip().splitlines()
    return [json.loads(l) for l in lines[-nb:][::-1]]