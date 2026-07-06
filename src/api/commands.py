"""Slash command router pour l'API server — même commandes que le TUI Axon."""
from __future__ import annotations

import asyncio
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import AsyncIterator

HANDLED = frozenset({"/help", "/keys", "/backend", "/model", "/graph", "/build"})


def is_command(text: str) -> bool:
    return text.strip().startswith("/")


def parse(text: str) -> tuple[str, str]:
    parts = text.strip().split(maxsplit=1)
    return parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")


async def dispatch(cmd: str, args: str, thread_id: str) -> AsyncIterator[str]:
    """Route une commande slash vers son handler. Yield du texte brut (pas SSE)."""
    handlers = {
        "/help":    _help,
        "/keys":    _keys,
        "/backend": _backend,
        "/model":   _model,
        "/graph":   _graph,
        "/build":   _build,
    }
    handler = handlers.get(cmd)
    if handler is None:
        yield f"Commande inconnue : `{cmd}`\nTape `/help` pour la liste.\n"
        return
    async for chunk in handler(args, thread_id):
        yield chunk


# ── /help ─────────────────────────────────────────────────────────────────────

async def _help(args: str, thread_id: str) -> AsyncIterator[str]:
    yield (
        "**Commandes Axon disponibles depuis Zed :**\n\n"
        "| Commande | Description |\n"
        "|---|---|\n"
        "| `/keys` | État des clés API multi-comptes |\n"
        "| `/keys reset` | Remet toutes les clés à sain |\n"
        "| `/keys reset <provider>` | Remet un provider à sain |\n"
        "| `/backend <b>` | Change le backend LLM (ollama_cloud · gemini · mistral) |\n"
        "| `/model <m>` | Change le modèle du backend actif |\n"
        "| `/graph [chemin]` | Génère GRAPH_REPORT.md + graph.json via graphify |\n"
        "| `/build <projet>` | Lance un build depuis spec.md, phase par phase |\n"
    )


# ── /keys ─────────────────────────────────────────────────────────────────────

async def _keys(args: str, thread_id: str) -> AsyncIterator[str]:
    from src.llm.key_pool import get_pool
    pool = get_pool()

    if args == "reset":
        pool.reset_all()
        yield "✓ Toutes les clés remises en état sain.\n"
        return

    if args.startswith("reset "):
        provider = args.split(None, 1)[1].strip()
        pool.reset_provider(provider)
        yield f"✓ Clés `{provider}` remises en état sain.\n"
        return

    rows = pool.status()
    if not rows:
        yield (
            "Aucune clé configurée.\n\n"
            "Ajouter dans `.env` :\n```\n"
            "OLLAMA_CLOUD_API_KEYS=key1,key2,key3\n"
            "GEMINI_API_KEYS=key1,key2\n"
            "FALLBACK_ORDER=ollama_cloud,gemini,mistral\n```\n"
        )
        return

    lines = ["| Provider | Clé | État | Cooldown |", "|---|---|---|---|"]
    for r in rows:
        if r["healthy"]:
            state, cd = "✓", ""
        else:
            secs = r["cooldown_left"]
            h, m = divmod(secs // 60, 60)
            cd = f"{h}h {m:02d}m" if h else f"{m}m"
            state = "✗"
        lines.append(f"| {r['provider']} | `{r['key_short']}` | {state} | {cd} |")
    yield "\n".join(lines) + "\n"


# ── /backend ──────────────────────────────────────────────────────────────────

_BACKENDS = ["ollama", "ollama_cloud", "gemini", "mistral", "groq"]


async def _backend(args: str, thread_id: str) -> AsyncIterator[str]:
    from src.infra.settings import settings
    if not args:
        yield f"Backend actif : **{settings.llm_backend}**\nOptions : {' · '.join(_BACKENDS)}\n"
        return
    b = args.strip().lower()
    if b not in _BACKENDS:
        yield f"Backend invalide : `{b}`\nOptions : {' · '.join(_BACKENDS)}\n"
        return
    settings.llm_backend = b
    yield f"✓ Backend → **{b}**\n"


# ── /model ────────────────────────────────────────────────────────────────────

async def _model(args: str, thread_id: str) -> AsyncIterator[str]:
    from src.infra.settings import settings
    backend = settings.llm_backend
    _model_attr = {
        "ollama_cloud": "ollama_cloud_model",
        "groq":         "groq_model",
        "gemini":       "gemini_model",
        "mistral":      "mistral_model",
        "ollama":       "ollama_model",
    }
    attr = _model_attr.get(backend, "ollama_model")
    if not args:
        yield f"Modèle actif [{backend}] : **{getattr(settings, attr)}**\n"
        return
    setattr(settings, attr, args.strip())
    yield f"✓ Modèle [{backend}] → **{args.strip()}**\n"


# ── /graph ────────────────────────────────────────────────────────────────────

async def _graph(args: str, thread_id: str) -> AsyncIterator[str]:
    from src.utils.paths import get_projects_dir
    from src.agents.shell.tools import get_cwd

    raw = args.strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = get_projects_dir() / raw
    else:
        p = Path(get_cwd())

    if not p.is_dir():
        yield f"✗ Dossier introuvable : `{p}`\n"
        return

    graphify_repo = Path.home() / "Documents" / "projets-perso" / "graphify"
    env = {**os.environ, "PYTHONPATH": str(graphify_repo)}
    loop = asyncio.get_running_loop()

    yield f"⚙ graphify extract · {p.name}…\n"

    try:
        proc = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, "-m", "graphify", "extract", str(p)],
                env=env, capture_output=True, text=True, timeout=300,
            ),
        )
    except subprocess.TimeoutExpired:
        yield "✗ Timeout extract (5 min)\n"
        return
    except Exception as e:
        yield f"✗ {e}\n"
        return

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-400:].strip()
        yield f"✗ exit {proc.returncode} :\n```\n{err}\n```\n"
        return

    yield f"⚙ graphify cluster · {p.name}…\n"

    try:
        proc2 = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, "-m", "graphify", "cluster-only", str(p), "--no-viz"],
                env=env, capture_output=True, text=True, timeout=120,
            ),
        )
    except Exception as e:
        yield f"⚠ Extract OK, cluster erreur : {e}\n"
        return

    if proc2.returncode != 0:
        err = (proc2.stderr or proc2.stdout or "")[-400:].strip()
        yield f"⚠ Extract OK, cluster exit {proc2.returncode} :\n```\n{err}\n```\n"
        return

    out_dir = p / "graphify-out"
    generated = [f for f in ("GRAPH_REPORT.md", "graph.json") if (out_dir / f).exists()]
    files = " · ".join(generated) if generated else "fichiers générés"
    yield f"✓ {files} → `{out_dir}`\n"


# ── /build ────────────────────────────────────────────────────────────────────

async def _build(args: str, thread_id: str) -> AsyncIterator[str]:
    project_name = args.strip()
    if not project_name:
        yield "Usage : `/build <nom-projet>`\nLe projet doit avoir un `spec.md`.\n"
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _progress(event: str, data: dict, result=None):
        text = _format_event(event, data)
        if text:
            loop.call_soon_threadsafe(queue.put_nowait, text)
        return None

    def _run() -> None:
        from src.agents.coding.build_runner import run_build
        from src.agents.coding.specialist import set_progress_callback
        from rich.console import Console

        try:
            set_progress_callback(_progress)
            fake_console = Console(file=io.StringIO(), no_color=True)
            run_build(project_name, fake_console)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, f"\n✗ Erreur build : {exc}\n")
        finally:
            set_progress_callback(None)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    yield f"🔨 Build · **{project_name}**\n\n"
    loop.run_in_executor(None, _run)

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

    yield "\n✓ Build terminé.\n"


def _format_event(event: str, data: dict) -> str:
    if event == "specialist:start":
        return f"▶ Specialist ({data.get('model', '?')})\n"
    if event == "specialist:backend_switch":
        return f"↺ {data.get('from')} → {data.get('to')}\n"
    if event == "specialist:compress":
        return "⟳ Compression contexte…\n"
    if event == "specialist:rate_limit":
        wait = data.get("wait", 0)
        exhausted = data.get("all_exhausted", False)
        return f"⏳ Rate limit {'(toutes clés épuisées) ' if exhausted else ''}— attente {wait}s…\n"
    if event == "dev_plan_create":
        steps = data.get("steps", [])
        return "📋 Plan :\n" + "".join(f"  ○ {s}\n" for s in steps)
    if event == "dev_plan_step_done":
        return f"  ✓ {data.get('label', '')}\n"
    if event == "propose_file_change":
        return f"  ✎ {data.get('path', '')}\n"
    if event == "shell_run":
        return f"  $ {str(data.get('command', ''))[:80]}\n"
    return ""
