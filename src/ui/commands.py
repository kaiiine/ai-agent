import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from rich.pretty import Pretty
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.markdown import Markdown

from .panels import config_table, command_panel, banner, _BOX, final_panel
from .transcript import save_transcript
from .config import SessionConfig
from src.infra.checkpoint import load_thread_cwd, save_thread_cwd, save_last_thread
from src.agents.shell.tools import get_cwd, set_cwd
from langchain_core.messages import SystemMessage
from src.orchestrator.graph import _SUMMARY_MARKER, _estimate_tokens, _cap_tool_messages


debug_state = {"enabled": False}

_COMMANDS = [
    ("/compact", "compresse le contexte de la session courante en un résumé dense"),
    ("/attach",            "joint un fichier (code, texte, PDF, image) à ton prochain message"),
    ("/paste",             "colle une image depuis le presse-papiers"),
    ("/attachments",       "liste les pièces jointes en attente"),
    ("/detach [fichier]",  "supprime une pièce jointe (ou toutes si sans argument)"),
    ("/letter",            "génère une lettre de motivation — attach ton CV d'abord, puis colle l'offre"),
    ("/upgrade",           "améliore une lettre existante — attach ton CV, colle la lettre puis l'offre"),
    ("/fiche",             "fiche de révision HTML/CSS depuis PDF(s) — /attach tes cours d'abord"),
    ("/exo",               "exercices interactifs HTML/JS (QCM, ouvert…) depuis PDF(s) — /attach tes cours"),
    ("/spec [prompt]",     "wizard interactif de spécification — l'IA pose des questions guidées"),
    ("/build [projet]",   "exécute spec.md par phases — 60-70% moins de tokens qu'une session unique"),
    ("/graph [projet]",   "génère GRAPH_REPORT.md + graph.json + notes Obsidian via graphify (subprocess direct)"),
    ("/mcp <sous-cmd>",   "serveurs MCP — list · add · remove · enable · disable · test [--deep] · tools · refresh · restart"),
    ("/clear",             "efface l'écran et réaffiche l'en-tête"),
    ("/new",               "démarre un nouveau thread de conversation"),
    ("/history",           "liste les threads passés et permet d'en reprendre un (flèches ↑↓)"),
    ("/help",              "affiche cette liste de commandes"),
    ("/keys [reset]",       "affiche l'état des clés API (multi-comptes) · /keys reset pour tout remettre sain"),
    ("/backend <b>",       "change le backend LLM — groq · ollama · ollama_cloud · gemini · mistral"),
    ("/model <nom>",       "change le modèle du backend actif (ex: llama3.1:8b, openai/gpt-oss-20b)"),
    ("/temp <val>",        "change la température (ex: /temp 0.7)"),
    ("/lang <fr|en>",      "force la langue de réponse"),
    ("/save",              "sauvegarde le transcript de la session"),
    ("/config",            "affiche la configuration courante"),
    ("/purge",             "supprime les blobs d'images bloqués dans l'état du thread courant"),
    ("/undo",              "annule les dernières modifications appliquées par le coding agent"),
    ("/mode <ask|auto>",   "mode d'édition — ask (valide fichier par fichier) ou auto (écrit sans confirmation)"),
    ("/branch",            "fork le thread actuel pour explorer une autre piste"),
    ("/debug",             "active/désactive le mode debug"),
    ("/dump",              "affiche tous les messages du thread"),
    ("q / exit",           "quitte Axon"),
    ("Ctrl+T",             "bascule le mode plan — l'IA planifie sans écrire"),
    ("Ctrl+O",             "attacher un fichier  (= /attach)"),
    ("Ctrl+P",             "coller une image     (= /paste)"),
    ("Ctrl+D",             "supprimer toutes les pièces jointes"),
    ("@fichier",           "injecte un fichier dans ton message — autocomplété par Tab"),
]

_BACKENDS = ["groq", "ollama", "ollama_cloud", "gemini", "mistral"]


_OLLAMA_FALLBACK = ["qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b"]
_GROQ_MODELS     = [
    "llama-3.3-70b-versatile",       # meilleur équilibre vitesse/qualité
    "compound-beta",                  # compound routing (Groq recommandé agentic)
    "deepseek-r1-distill-llama-70b", # raisonnement
    "qwen-qwq-32b",                  # raisonnement léger
    "llama-3.1-8b-instant",          # rapide/léger
    "openai/gpt-oss-20b",
]
_CLOUD_MODELS    = [
    "minimax-m3:cloud",
    "gpt-oss:120b-cloud",
    "gpt-oss:20b-cloud",
    "glm-5.2:cloud",
    "glm-4.7:cloud",
    "gemma4:31b-cloud",
    "qwen3-coder:480b-cloud",
    "qwen3.5:cloud",
    "qwen3-next:80b-cloud",
    "kimi-k2:1t-cloud"
]
_GEMINI_MODELS   = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview", 
    "gemini-2.5-flash",        
    "gemini-2.5-pro",          
    "gemini-1.5-flash",       
]
_MISTRAL_MODELS = [
    "mistral-small-2603",
]


def _get_ollama_local_models() -> list[str]:
    import subprocess
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().splitlines()[1:]  # skip header
        models = [l.split()[0] for l in lines if l.strip()]
        return models if models else _OLLAMA_FALLBACK
    except Exception:
        return _OLLAMA_FALLBACK


def _get_model_options(backend: str) -> list[str]:
    if backend == "groq":
        return _GROQ_MODELS
    if backend == "ollama_cloud":
        return _CLOUD_MODELS
    if backend == "gemini":
        return _GEMINI_MODELS
    if backend == "mistral":
        return _MISTRAL_MODELS
    return _get_ollama_local_models()


def _current_model(settings) -> str:
    if settings.llm_backend == "groq":
        return settings.groq_model
    if settings.llm_backend == "ollama_cloud":
        return settings.ollama_cloud_model
    if settings.llm_backend == "gemini":
        return settings.gemini_model
    if settings.llm_backend == "mistral":
        return settings.mistral_model
    return settings.ollama_model


def _set_model(settings, model: str) -> None:
    if settings.llm_backend == "groq":
        settings.groq_model = model
    elif settings.llm_backend == "ollama_cloud":
        settings.ollama_cloud_model = model
    elif settings.llm_backend == "gemini":
        settings.gemini_model = model
    elif settings.llm_backend == "mistral":
        settings.mistral_model = model
    else:
        settings.ollama_model = model


def _handle_history(cfg: SessionConfig, state: dict, console) -> None:
    """Picker flèches pour naviguer dans les threads passés."""
    from src.infra.checkpoint import list_threads, save_last_thread, get_recent_messages
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style
    from rich.rule import Rule

    _PT_STYLE = Style.from_dict({
        "title":    "bold ansiyellow",
        "selected": "bold ansiyellow",
        "normal":   "ansiwhite",
        "meta":     "ansiyellow",
        "preview":  "ansibrightblack",
        "new":      "bold ansigreen",
        "hint":     "ansiyellow",
    })

    threads = list_threads()

    # Entrée spéciale "nouveau thread" en tête de liste
    _NEW = "__new__"
    entries = [_NEW] + [t["thread_id"] for t in threads]
    thread_map = {t["thread_id"]: t for t in threads}

    idx = [0]
    # Pré-sélectionne le thread actif
    try:
        idx[0] = entries.index(cfg.thread_id)
    except ValueError:
        idx[0] = 0

    def _label(tid: str, selected: bool) -> list:
        arrow = "  ▶  " if selected else "     "
        cls_a = "class:selected" if selected else "class:normal"
        cls_m = "class:meta"
        cls_p = "class:preview"

        if tid == _NEW:
            return [(cls_a if selected else "class:new", f"{arrow}+ nouveau thread\n")]

        t = thread_map.get(tid, {})
        updated  = t.get("updated_at", "")
        preview  = t.get("preview", "")
        active   = " ★" if tid == cfg.thread_id else ""
        short_id = tid[:8] if len(tid) > 8 else tid

        parts = []
        parts.append((cls_a, f"{arrow}{short_id}{active}"))
        if updated:
            parts.append((cls_m, f"  {updated}"))
        parts.append(("", "\n"))
        if preview:
            parts.append((cls_p, f"       {preview}\n"))
        return parts

    def get_tokens():
        parts: list = [("class:title", "  historique des conversations\n\n")]
        for i, tid in enumerate(entries):
            parts.extend(_label(tid, i == idx[0]))
        parts.append(("class:hint", "\n  ↑↓ · Entrée pour reprendre · Échap pour annuler"))
        return parts

    kb = KeyBindings()

    @kb.add("down")
    @kb.add("tab")
    def _fwd(event): idx[0] = (idx[0] + 1) % len(entries)

    @kb.add("up")
    @kb.add("s-tab")
    def _bwd(event): idx[0] = (idx[0] - 1) % len(entries)

    @kb.add("enter")
    def _ok(event): event.app.exit(result=entries[idx[0]])

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event): event.app.exit(result=None)

    height = min(len(entries) * 2 + 6, 30)
    app = Application(
        layout=Layout(Window(FormattedTextControl(get_tokens, focusable=True), height=height)),
        key_bindings=kb,
        style=_PT_STYLE,
        full_screen=False,
        mouse_support=False,
    )
    chosen = app.run()

    if chosen is None:
        return command_panel("annulé")

    if chosen == _NEW:
        cfg.thread_id = str(uuid.uuid4())[:8]
        state["messages"] = []
        save_last_thread(cfg.thread_id)
        return command_panel(f"nouveau thread : {cfg.thread_id}")

    # Reprendre un thread existant
    if chosen != cfg.thread_id:
        cfg.thread_id = chosen
        state["messages"] = []
        save_last_thread(chosen)
        saved_cwd = load_thread_cwd(chosen)
        if saved_cwd:
            set_cwd(saved_cwd)

        # Affiche l'historique complet du thread repris
        if console:
            console.print()
            console.print(Rule("reprise de session", characters="·", style="dim color(214)"))
            msgs = get_recent_messages(chosen)
            visible = [m for m in msgs if m["role"] in ("human", "ai") and m["content"].strip()]
            hidden = len(visible) - 50
            if hidden > 0:
                visible = visible[-50:]
            if hidden > 0:
                console.print(Text(f"  … {hidden} messages plus anciens", style="dim"))
                console.print()
            for m in visible:
                role, content = m["role"], m["content"].strip()
                if role == "human":
                    t = Text()
                    t.append("  ›  ", style="bold color(214)")
                    t.append(content, style="bold color(214)")
                    console.print(t)
                elif role == "ai":
                    clean = re.sub(
                        r'<axon:plan>.*?</axon:plan>\s*', '', content, flags=re.DOTALL
                    ).strip()
                    if clean:
                        console.print(final_panel(clean))
            console.print()

        return command_panel(f"thread repris : {chosen[:8]}")

    return command_panel(f"déjà sur ce thread : {chosen[:8]}")


def handle_slash(cmd: str, state: dict, cfg: SessionConfig, graph=None, console=None):
    cmd = cmd.strip()

    if cmd == "/clear":
        rs = clear(console)
        return rs

    if cmd in {"/help", "/h"}:
        from rich.table import Table
        from rich import box
        tbl = Table(box=box.SIMPLE_HEAD, show_header=False, padding=(0, 2))
        tbl.add_column("cmd",  style="color(214)", no_wrap=True)
        tbl.add_column("desc", style="dim")
        for c, d in _COMMANDS:
            tbl.add_row(c, d)
        return Panel(tbl, box=_BOX, border_style="dim color(214)", title="commandes", padding=(0, 1))

    if cmd == "/new":
        cfg.thread_id = str(uuid.uuid4())[:8]
        state["messages"] = []
        save_last_thread(cfg.thread_id)
        from src.agents.shell.tools import set_cwd as _set_cwd
        _set_cwd(Path.home())
        save_thread_cwd(cfg.thread_id, str(Path.home()))
        clear(console)
        return None
        # return command_panel(f"nouveau thread : {cfg.thread_id}  ·  {Path.home()}")

    if cmd == "/history":
        return _handle_history(cfg, state, console)

    if cmd == "/mcp" or cmd.startswith("/mcp "):
        from src.mcp_client.commands import handle_mcp
        from src.mcp_client.runtime import mcp_runtime

        try:
            return command_panel(handle_mcp(cmd.split()[1:], mcp_runtime()))
        except Exception as e:
            return command_panel(f"erreur mcp : {e}", error=True)

    if cmd.startswith("/keys"):
        from src.llm.key_pool import get_pool
        from rich.table import Table
        pool = get_pool()
        parts = cmd.split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        if arg == "reset":
            pool.reset_all()
            return command_panel("toutes les clés remises en état sain")

        if arg.startswith("reset "):
            provider = arg.split(None, 1)[1]
            pool.reset_provider(provider)
            return command_panel(f"clés {provider} remises en état sain")

        rows = pool.status()
        if not rows:
            return command_panel(
                "aucune clé configurée.\n"
                "Ajouter dans .env :\n"
                "  OLLAMA_CLOUD_API_KEYS=key1,key2,key3\n"
                "  GEMINI_API_KEYS=key1,key2\n"
                "  FALLBACK_ORDER=ollama_cloud,gemini,mistral",
                error=False,
            )
        t = Table(show_header=True, header_style="bold", box=_BOX, border_style="dim")
        t.add_column("Provider", style="dim")
        t.add_column("Clé", style="dim")
        t.add_column("État")
        t.add_column("Cooldown")
        for r in rows:
            if r["healthy"]:
                state_str = "[green]✓[/green]"
                cooldown  = ""
            else:
                secs = r["cooldown_left"]
                h, m = divmod(secs // 60, 60)
                cooldown = f"{h}h {m:02d}m" if h else f"{m}m"
                state_str = "[red]✗[/red]"
            t.add_row(r["provider"], r["key_short"], state_str, cooldown)
        return Panel(t, box=_BOX, border_style="dim", title="clés API")

    if cmd.startswith("/backend"):
        from src.infra.settings import settings
        from src.ui.picker import pick
        parts = cmd.split(maxsplit=1)
        if len(parts) == 1:
            # Arrow-key picker
            chosen = pick(_BACKENDS, title="backend LLM", current=settings.llm_backend)
            if chosen is None:
                return command_panel("annulé")
            settings.llm_backend = chosen
            return command_panel(f"backend : {chosen}")
        b = parts[1].strip().lower()
        if b not in _BACKENDS:
            return command_panel("backend invalide. options : groq · ollama · ollama_cloud · gemini · mistral", error=True)
        settings.llm_backend = b
        return command_panel(f"backend : {b}")

    if cmd.startswith("/model"):
        from src.infra.settings import settings
        from src.ui.picker import pick
        parts = cmd.split(maxsplit=1)
        if len(parts) == 1:
            # Arrow-key picker selon le backend actif
            options = _get_model_options(settings.llm_backend)
            current = _current_model(settings)
            chosen = pick(options, title=f"modèle  [{settings.llm_backend}]", current=current)
            if chosen is None:
                return command_panel("annulé")
            _set_model(settings, chosen)
            return command_panel(f"modèle [{settings.llm_backend}] : {chosen}")
        model = parts[1].strip()
        _set_model(settings, model)
        return command_panel(f"modèle [{settings.llm_backend}] : {model}")

    if cmd.startswith("/temp "):
        from src.infra.settings import settings
        try:
            settings.temperature = float(cmd.split(" ", 1)[1])
            return command_panel(f"température : {settings.temperature}")
        except ValueError:
            return command_panel("valeur invalide. exemple : /temp 0.2", error=True)

    if cmd.startswith("/lang "):
        lp = cmd.split(" ", 1)[1].strip().lower()
        if lp in {"fr", "en", "auto"}:
            cfg.lang_pref = lp
            from src.orchestrator.graph import set_lang_pref
            set_lang_pref(lp)
            return command_panel(f"langue : {cfg.lang_pref}")
        return command_panel("langue invalide. options : fr · en · auto", error=True)

    if cmd == "/save":
        try:
            if graph:
                config = {"configurable": {"thread_id": cfg.thread_id}}
                snapshot = graph.get_state(config)
                messages = snapshot.values.get("messages", []) if snapshot.values else []
                p = save_transcript(cfg.thread_id, {"messages": messages})
            else:
                p = save_transcript(cfg.thread_id, state)
            return command_panel(f"transcript sauvegardé : {p}")
        except Exception as e:
            return command_panel(f"erreur sauvegarde : {e}", error=True)

    if cmd == "/config":
        return Panel(config_table(cfg), box=_BOX, border_style="dim", title="config")

    if cmd.startswith("/mode"):
        from src.ui.edit_mode import get_mode, set_mode
        from src.ui.picker import pick
        parts = cmd.split(maxsplit=1)
        if len(parts) == 1:
            chosen = pick(["ask", "auto"], title="mode édition", current=get_mode())
            if chosen is None:
                return command_panel("annulé")
            set_mode(chosen)
            return command_panel(f"mode édition : {chosen}")
        m = parts[1].strip().lower()
        if set_mode(m):
            return command_panel(f"mode édition : {m}")
        return command_panel("mode invalide. options : ask · auto", error=True)

    if cmd == "/branch":
        old_thread = cfg.thread_id
        new_thread = str(uuid.uuid4())[:8]

        # Copy current checkpoint state to the new thread
        if graph:
            try:
                old_config = {"configurable": {"thread_id": old_thread}}
                snapshot = graph.get_state(old_config)
                msgs = snapshot.values.get("messages", []) if snapshot.values else []
                if msgs:
                    new_config = {"configurable": {"thread_id": new_thread}}
                    graph.update_state(new_config, {"messages": msgs})
            except Exception:
                pass  # branch with empty state is still useful

        cfg.thread_id = new_thread
        state["messages"] = []
        save_last_thread(new_thread)
        save_thread_cwd(new_thread, str(get_cwd()))
        return command_panel(f"branche créée : {old_thread[:8]} → {new_thread}")

    if cmd == "/undo":
        from src.agents.coding.pending import snapshots
        from .panels import ACCENT
        if not snapshots:
            return command_panel("rien à annuler — aucune modification récente")
        paths = snapshots.paths
        if console:
            console.print(Rule(characters="·", style=f"dim {ACCENT}"))
            for p in paths:
                t = Text()
                t.append("  ↩  ", style=f"bold {ACCENT}")
                t.append(p, style="dim")
                console.print(t)
        restored = snapshots.restore_all()
        n = len(restored)
        return command_panel(f"{n} fichier{'s' if n > 1 else ''} restauré{'s' if n > 1 else ''}")

    if cmd == "/debug":
        debug_state["enabled"] = not debug_state["enabled"]
        status = "on" if debug_state["enabled"] else "off"
        return command_panel(f"debug : {status}")

    if cmd == "/dump":
        try:
            if graph:
                config = {"configurable": {"thread_id": cfg.thread_id}}
                snapshot = graph.get_state(config)
                messages = snapshot.values.get("messages", []) if snapshot.values else []
                return Panel(Pretty(messages, expand_all=True), box=_BOX, border_style="dim", title="dump")
        except Exception as e:
            return command_panel(f"erreur dump : {e}", error=True)
        return Panel(Pretty(state["messages"], expand_all=True), box=_BOX, border_style="dim", title="dump")

    if cmd.startswith("/graph"):
        from src.agents.shell.tools import get_cwd
        from src.utils.paths import get_projects_dir

        raw_path = cmd[len("/graph"):].strip()
        chemin_seul = raw_path.replace("--update", "").strip()
        if chemin_seul:
            project_path = Path(chemin_seul).expanduser()
            if not project_path.is_absolute():
                project_path = get_projects_dir() / chemin_seul
        else:
            project_path = Path(get_cwd())

        if not project_path.is_dir():
            return command_panel(f"dossier introuvable : {project_path}", error=True)

        graphify_repo = Path.home() / "Documents" / "projets-perso" / "graphify"
        env = {**os.environ, "PYTHONPATH": str(graphify_repo)}

        out_dir = project_path / "graphify-out"

        # `/graph <projet> --update` réextrait SANS appel modèle — c'est la
        # commande que graphify prévoit pour suivre le code. Sans elle, le
        # graphe vieillissait en silence : celui de ce dépôt annonçait
        # « Built from commit bdeba46c » avec sept commits d'écart, et rendait
        # des chemins de fichiers déplacés depuis.
        mise_a_jour = "--update" in raw_path
        if mise_a_jour and (out_dir / "graph.json").exists():
            if console:
                t = Text()
                t.append("  ⚙  ", style="bold color(214)")
                t.append(f"graphify update · {project_path.name} (sans modèle)…", style="dim")
                console.print(t)
            try:
                proc_u = subprocess.run(
                    [sys.executable, "-m", "graphify", "update", str(project_path)],
                    env=env, capture_output=True, text=True, timeout=300,
                )
            except Exception as e:
                return command_panel(f"graphify update erreur : {e}", error=True)
            if proc_u.returncode != 0:
                err = (proc_u.stderr or proc_u.stdout or "")[-400:].strip()
                return command_panel(f"graphify update erreur :\n{err}", error=True)
            return command_panel(f"✓  graphe mis à jour  →  {out_dir}")

        if console:
            t = Text()
            t.append("  ⚙  ", style="bold color(214)")
            t.append(f"graphify extract · {project_path.name}…", style="dim")
            console.print(t)

        # Step 1: extract (AST + semantic)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "graphify", "extract", str(project_path)],
                env=env, capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            return command_panel("graphify extract timeout (5 min) — projet trop volumineux ?", error=True)
        except Exception as e:
            return command_panel(f"graphify erreur : {e}", error=True)

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-600:].strip()
            return command_panel(f"graphify extract erreur (exit {proc.returncode}) :\n{err}", error=True)

        # Step 2: cluster-only → generates GRAPH_REPORT.md
        if console:
            t2 = Text()
            t2.append("  ⚙  ", style="bold color(214)")
            t2.append(f"graphify cluster · {project_path.name}…", style="dim")
            console.print(t2)

        try:
            proc2 = subprocess.run(
                [sys.executable, "-m", "graphify", "cluster-only", str(project_path), "--no-viz"],
                env=env, capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return command_panel("graphify cluster timeout — extract OK, relance /graph pour le rapport", error=True)
        except Exception as e:
            return command_panel(f"graphify cluster erreur : {e}", error=True)

        generated = []
        if (out_dir / "GRAPH_REPORT.md").exists():
            generated.append("GRAPH_REPORT.md")
        if (out_dir / "graph.json").exists():
            generated.append("graph.json")
        files = " · ".join(generated) if generated else "graph généré"
        return command_panel(f"✓  {files}  →  {out_dir}")

    if cmd == "/compact":
        if not graph:
            return command_panel("pas de graph actif", error=True)
        try:
            from src.infra.settings import settings
            from src.orchestrator.graph import _compress_context, _chat_node_factory
            from src.llm.models import make_llm, make_llm_ollama_cloud, make_llm_groq, make_llm_gemini, make_llm_mistral
            from langchain_core.messages import RemoveMessage

            _factories = {
                "groq":         make_llm_groq,
                "ollama_cloud": make_llm_ollama_cloud,
                "ollama":       make_llm,
                "gemini":       make_llm_gemini,
                "mistral":      make_llm_mistral,
            }
            backend = settings.llm_backend
            factory = _factories.get(backend, make_llm_ollama_cloud)

            config = {"configurable": {"thread_id": cfg.thread_id}}
            snapshot = graph.get_state(config)
            messages = snapshot.values.get("messages", []) if snapshot.values else []

            if len(messages) <= 3:
                return command_panel("contexte trop court pour compresser")

            already_compacted = any(
                isinstance(m, SystemMessage)
                and _SUMMARY_MARKER in str(m.content)
                for m in messages
            )

            if already_compacted and len(messages) < 12:
                return command_panel(
                    "contexte déjà compacté récemment"
                )

            plain_llm = factory()
            before_tokens = _estimate_tokens(messages)

            messages = _cap_tool_messages(messages)
            compressed, removed = _compress_context(messages, plain_llm, backend)

            after_tokens = _estimate_tokens(compressed)
            freed = before_tokens - after_tokens

            # Persist dans LangGraph
            removals = [RemoveMessage(id=m.id) for m in removed if getattr(m, "id", None)]
            summary = next(
                (
                    m for m in compressed
                    if isinstance(m, SystemMessage)
                    and _SUMMARY_MARKER in str(m.content)
                ),
                None,
            )
            updates = removals + ([summary] if summary else [])
            if updates:
                graph.update_state(config, {"messages": updates})

            return command_panel(
                f"contexte compressé — "
                f"{before_tokens:,} → {after_tokens:,} tokens "
                f"(-{freed:,})"
            )
        except Exception as e:
            return command_panel(f"erreur compression : {e}", error=True)

    return None


def clear(console=None):
    if console:
        console.clear()
        console.print(banner())
    return None