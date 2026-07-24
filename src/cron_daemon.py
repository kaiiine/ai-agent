#!/usr/bin/env python3
"""Axon Cron Daemon — exécute les tâches planifiées en background."""

from __future__ import annotations
import json
import signal
import sys
import os
import re
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from src.agents.cron.store import get_tasks, update_task, deactivate_task, append_log
from src.agents.slack.tools import _client, _resolve_channel
from src.infra.settings import settings
from src.llm.models import make_llm_gemini, make_llm_mistral, make_llm_ollama_cloud

PID_FILE = Path.home() / ".axon" / "cron.pid"
RELOAD_INTERVAL = 10 # sec
_SYSTEM = """\
Tu es un agent de monitoring autonome. Exécute la tâche demandée.
Réponds UNIQUEMENT avec un objet JSON valide (pas de markdown) :
{
  "notify": true,
  "message": "Texte court de la notification (max 200 chars)",
  "result_summary": "État actuel à mémoriser pour la prochaine exécution",
  "stop": false
}
Si rien de nouveau à signaler : notify=false. Si la stop_condition est remplie : stop=true.
"""


def _notify_desktop(title: str, message: str) -> None:
    try:
        subprocess.run(["notify-send", "-u", "normal", title, message], timeout=5)
    except Exception:
        pass

def _notify_slack(message: str) -> None:
    try:
        client = _client()
        channel = os.environ.get("SLACK_CRON_CHANNEL", "test-cron")
        channelId = _resolve_channel(client, channel)
        client.chat_postMessage(channel=channelId, text=message)
    except Exception:
        pass
    


def _send_notification(channels: list[str], description: str, message: str) -> None:
    if "desktop" in channels:
        _notify_desktop(f"Axon · {description}", message)
    if "slack" in channels:
        _notify_slack(f"*{description}*\n{message}")

# TODO: Move this function in the models.py file
def _make_llm():
    factories = {
        "gemini": make_llm_gemini,
        "mistral": make_llm_mistral,
        "ollama_cloud": make_llm_ollama_cloud,
    }
    return factories.get(settings.llm_backend, make_llm_ollama_cloud)()



def _run_task(task_id: str) -> None:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.prebuilt import create_react_agent
    from src.agents.search.tools import web_search_news, web_research_report
    from src.agents.shell.tools import shell_run

    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task or not task.get("active"):
        return

    start = time.perf_counter()
    log_entry: dict = {
        "ts": datetime.now().isoformat(),
        "status": "ok",
        "notified": False,
        "message": "",
        "result_summary": "",
        "duration_ms": 0,
        "error": None,
    }

    try:
        prompt = task["prompt"].replace("{last_result}", str(task.get("last_result") or ""))
        if task.get("stop_condition"):
            prompt += f"\n\nStop condition: {task['stop_condition']}"

        llm = _make_llm()
        tools = [web_search_news, web_research_report, shell_run]
        agent = create_react_agent(llm, tools, prompt=_SYSTEM)
        result_state = agent.invoke({"messages": [HumanMessage(content=prompt)]})
        raw = result_state["messages"][-1].content

        m = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(m.group()) if m else {}

        notify  = result.get("notify", False)
        message = result.get("message", "")
        summary = result.get("result_summary", "")
        stop    = result.get("stop", False)

        if notify and message:
            _send_notification(task["notify_channels"], task["description"], message)
            log_entry["notified"] = True
            log_entry["message"] = message

        log_entry["result_summary"] = summary
        log_entry["status"] = "skipped" if stop else "ok"

        update_task(task["id"], last_run=datetime.now().isoformat(), last_result=summary)

        if stop:
            deactivate_task(task["id"])
            _notify_desktop(f"Axon · {task['description']}", "Tâche terminée (condition remplie).")

    except Exception as e:
        log_entry["status"] = "error"
        log_entry["error"] = str(e)

    log_entry["duration_ms"] = int((time.perf_counter() - start) * 1000)
    append_log(task["id"], log_entry)


# ── Scheduler ────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()
_known_ids: set[str] = set()

def _reload_tasks() -> None:
    tasks = get_tasks(active_only=True)
    currentIds = {t["id"] for t in tasks}

    for job_id in list(_known_ids):
        if job_id not in currentIds:
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass
            _known_ids.discard(job_id)
    
    now = datetime.now()
    for task in tasks:
        if task["id"] in _known_ids:
            continue

        run_at = task.get("run_at")
        if run_at:
            dt = datetime.fromisoformat(run_at)
            if dt < now:
                deactivate_task(task["id"])
                append_log(task["id"], {
                    "ts": now.isoformat(),
                    "status": "skipped",
                    "error": "daemon was down",
                    "notified": False,
                    "message": "",
                    "result_summary": "",
                    "duration_ms":0,
                })
                _notify_desktop(f"Axon · {task['description']}", "Tâche one-shot manquée (daemon inactif). Recréer si besoin.")
                continue
            trigger = DateTrigger(run_date=dt)
        else:
            trigger = IntervalTrigger(seconds=task["interval_sec"])
        
        scheduler.add_job(
            _run_task,
            trigger=trigger,
            id=task["id"],
            args=[task["id"]],
            max_instances=1,
            misfire_grace_time=30,
        )
        _known_ids.add(task["id"])


def _shutdown(signum, frame):
    print("axon-cron: arrêt...")
    scheduler.shutdown(wait=False)
    PID_FILE.unlink(missing_ok=True)
    sys.exit(0)

if __name__ == "__main__":
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    scheduler.start()
    _reload_tasks()

    print(f"axon-cron démarré (PID {os.getpid()})")

    while True:
        time.sleep(RELOAD_INTERVAL)
        _reload_tasks()
    
    