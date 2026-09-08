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
from src.infra import alerte, trace
from src.infra.settings import settings
from src.llm.models import make_llm_gemini, make_llm_mistral, make_llm_ollama_cloud, make_llm_nvidia

from src.llm.prompts.cron import SYSTEME as _SYSTEM

from src.infra import chemins as _chemins

PID_FILE = _chemins.pid_cron()
RELOAD_INTERVAL = 10 # sec


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
def _verdict_de_veille(task, veille, reponse, log_entry) -> tuple[bool, str]:
    """(faut-il prévenir, quoi dire) pour une tâche de veille."""
    from src.agents.cron.surveillance import doit_alerter, extraire

    valeur = extraire(reponse)
    alerte, raison = doit_alerter(veille, valeur)
    log_entry["surveillance"] = {"valeur": valeur, "raison": raison, "alerte": alerte}

    # Référence mise à jour même sans alerte : sinon la comparaison suivante se
    # ferait sur une valeur périmée.
    if valeur is not None and valeur != veille.get("derniere") and not log_entry.get("essai"):
        update_task(task["id"], surveillance={**veille, "derniere": valeur})

    if not alerte:
        return False, ""
    quoi = veille.get("quoi", "la valeur suivie")
    return True, f"{task['description']} — {quoi} : {raison}"


#: Les statuts par lesquels un outil refuse.
_STATUTS_DE_REFUS = ("requires_confirmation", "blocked")


def _refus_d_outil(messages: list) -> list[str]:
    """Les commandes qu'un outil a refusé d'exécuter pendant ce tour.

    Un refus rend un statut, il ne lève pas : sans cette lecture, une tâche
    entièrement bloquée loguerait « ok ».
    """
    refuses: list[str] = []
    for message in messages:
        contenu = getattr(message, "content", None)
        if not isinstance(contenu, str) or not contenu.strip().startswith("{"):
            continue
        try:
            charge = json.loads(contenu)
        except (ValueError, TypeError):
            continue
        if isinstance(charge, dict) and charge.get("status") in _STATUTS_DE_REFUS:
            refuses.append(str(charge.get("command") or charge.get("target") or "?"))
    return refuses


def _make_llm():
    from src.llm.backends import fabriques as _registre

    factories = _registre()
    return factories.get(settings.llm_backend, make_llm_ollama_cloud)()



def _run_task(task_id: str, *, essai: bool = False) -> dict | None:
    """Exécute une tâche planifiée. Rend son entrée de journal.

    `essai=True` : même chemin, effets suspendus — rien n'est notifié ni persisté.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.prebuilt import create_react_agent
    from src.agents.search.tools import web_search_news, web_research_report
    from src.agents.shell.autorisation import declarer, retirer
    from src.agents.shell.tools import shell_run
    from src.agents.quant.conversation.tools import betting_recommend
    from src.agents.quant.tools import (
        winamax_odds_fetch, sports_stats_fetch, probability_compute,
        ev_analyze, same_match_combo_analyze, parlay_analyze,
    )

    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return None
    if not task.get("active") and not essai:
        return None

    # Un run par exécution de tâche. La source `cron` sépare ces lignes de celles
    # de la conversation : c'est le chemin sans témoin, celui qu'on veut pouvoir
    # isoler d'un coup dans `axon trace`.
    run_id = trace.nouveau_run("cron")

    start = time.perf_counter()
    log_entry: dict = {
        "essai": essai,
        "ts": datetime.now().isoformat(),
        "status": "ok",
        "notified": False,
        "message": "",
        "result_summary": "",
        "duration_ms": 0,
        "error": None,
    }

    # Sans permissions déclarées, la tâche ne lance que ce qui est reconnu sûr :
    # personne n'est là pour répondre à une confirmation.
    source_autorisation = f"cron:{task['id']}"
    declarer(source_autorisation, list(task.get("commandes_autorisees") or []))

    try:
        prompt = task["prompt"].replace("{last_result}", str(task.get("last_result") or ""))
        if task.get("stop_condition"):
            prompt += f"\n\nStop condition: {task['stop_condition']}"

        llm = _make_llm()
        tools = [
            web_search_news, web_research_report, shell_run,
            # L'UNIQUE chemin de recommandation, ici aussi : une tâche planifiée
            # « les meilleurs paris du jour » disposait des six outils de données
            # mais d'aucun capable de recommander — et poussait le résultat sur
            # Slack sans qu'aucun humain ne soit devant l'écran.
            betting_recommend,
            winamax_odds_fetch, sports_stats_fetch, probability_compute,
            ev_analyze, same_match_combo_analyze, parlay_analyze,
        ]
        agent = create_react_agent(llm, tools, prompt=_SYSTEM)
        result_state = agent.invoke({"messages": [HumanMessage(content=prompt)]})
        raw = result_state["messages"][-1].content

        m = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(m.group()) if m else {}

        notify  = result.get("notify", False)
        message = result.get("message", "")
        summary = result.get("result_summary", "")
        stop    = result.get("stop", False)

        # Garde de provenance, comme dans le graphe conversationnel. Une
        # notification est une réponse — poussée sur Slack ou le bureau sans
        # personne devant l'écran pour la relire. C'est la sortie qui mérite le
        # PLUS d'être vérifiée, pas la moins.
        if notify and message:
            from src.agents.quant.conversation.evidence import (
                extract_evidence,
                has_structured_output,
            )
            from src.agents.quant.conversation.guard import enforce as _enforce_betting

            _msgs = result_state.get("messages") or []
            _verdict = _enforce_betting(
                message, extract_evidence(_msgs),
                has_structured_output=has_structured_output(_msgs))
            if _verdict.blocked:
                log_entry["error"] = f"réponse de pari non sourcée ({_verdict.reason})"
                message = (f"[{_verdict.reason}] Réponse bloquée : aucune sortie "
                           "structurée ne l'appuie. Aucun pari n'est proposé.")

        # Une veille ne prévient que si la valeur a bougé.
        veille = task.get("surveillance")
        if veille:
            notify, message = _verdict_de_veille(task, veille, raw, log_entry)

        if notify and message:
            if essai:
                log_entry["aurait_notifie"] = {
                    "canaux": task["notify_channels"], "message": message}
            else:
                _send_notification(task["notify_channels"], task["description"], message)
                log_entry["notified"] = True
            log_entry["message"] = message

        log_entry["result_summary"] = summary
        log_entry["status"] = "skipped" if stop else "ok"

        # Un refus d'outil doit écraser le statut optimiste : sinon une tâche
        # entièrement bloquée passe pour un succès.
        refus = _refus_d_outil(result_state.get("messages") or [])
        for commande in refus:
            # Le démon n'utilise pas `CachedToolNode` — il a son propre graphe
            # (`create_react_agent`), donc rien n'a inscrit ces refus. Tant que
            # les deux graphes n'en font qu'un, la trace doit être alimentée des
            # deux côtés, sinon le chemin non surveillé est aussi le moins vu.
            trace.inscrire(trace.Action(
                genre=trace.OUTIL, outil="shell_run", cible=str(commande)[:200],
                policy=trace.REFUSE, resultat=trace.BLOQUE, erreur="blocked",
                verification=trace.NON_VERIFIE))
        if refus:
            log_entry["status"] = "error"
            log_entry["error"] = (
                f"{len(refus)} commande(s) non autorisée(s), aucune personne pour "
                f"confirmer : {refus[0]}. Déclare-les dans `commandes_autorisees` "
                f"de la tâche si elles doivent tourner sans surveillance.")

        if not essai:
            update_task(task["id"], last_run=datetime.now().isoformat(),
                        last_result=summary)

        if stop and not essai:
            deactivate_task(task["id"])
            _notify_desktop(f"Axon · {task['description']}", "Tâche terminée (condition remplie).")

    except Exception as e:
        log_entry["status"] = "error"
        log_entry["error"] = str(e)
    finally:
        # Retiré dans tous les cas : une permission qui survit profiterait au
        # tour suivant, qui ne l'a pas demandée.
        retirer(source_autorisation)

    log_entry["duration_ms"] = int((time.perf_counter() - start) * 1000)

    trace.inscrire(trace.Action(
        genre=trace.TACHE,
        outil=task["id"],
        cible=str(task.get("description") or "")[:200],
        resultat=(trace.ERREUR if log_entry["status"] == "error" else trace.OK),
        erreur=str(log_entry.get("error") or "")[:80],
        latence_ms=log_entry["duration_ms"],
        verification=trace.NON_VERIFIE,
        extra={"notifie": bool(log_entry.get("notified")), "essai": essai},
    ))

    # L'alerting, sur le seul chemin que personne ne regarde. En essai on ne
    # notifie pas — même règle que le reste de `cron-test` : l'exécution est
    # réelle, les effets sont suspendus, et on DIT ce qui aurait été envoyé.
    raisons = alerte.du_run(run_id)
    if raisons:
        if essai:
            log_entry["aurait_alerte"] = raisons
        else:
            _send_notification(task.get("notify_channels") or ["desktop"],
                               f"{task.get('description', task['id'])} — anomalie",
                               "\n".join(f"• {r}" for r in raisons))

    if not essai:
        append_log(task["id"], log_entry)
    return log_entry


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
    
    