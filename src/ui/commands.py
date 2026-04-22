import uuid
from rich.pretty import Pretty
from rich.panel import Panel

from .panels import config_table, command_panel, banner, _BOX
from .transcript import save_transcript
from .config import SessionConfig

debug_state = {"enabled": False}

_COMMANDS = [
    ("/attach",            "joint un fichier (code, texte, PDF, image) à ton prochain message"),
    ("/paste",             "colle une image depuis le presse-papiers"),
    ("/attachments",       "liste les pièces jointes en attente"),
    ("/detach [fichier]",  "supprime une pièce jointe (ou toutes si sans argument)"),
    ("/letter",            "génère une lettre de motivation — attach ton CV d'abord, puis colle l'offre"),
    ("/upgrade",           "améliore une lettre existante — attach ton CV, colle la lettre puis l'offre"),
    ("/clear",             "efface l'écran et réaffiche l'en-tête"),
    ("/new",               "démarre un nouveau thread de conversation"),
    ("/history",           "liste les threads passés et permet d'en reprendre un (flèches ↑↓)"),
    ("/help",              "affiche cette liste de commandes"),
    ("/backend <b>",       "change le backend LLM — groq · ollama · ollama_cloud · gemini"),
    ("/model <nom>",       "change le modèle du backend actif (ex: llama3.1:8b, openai/gpt-oss-20b)"),
    ("/temp <val>",        "change la température (ex: /temp 0.7)"),
    ("/lang <fr|en>",      "force la langue de réponse"),
    ("/save",              "sauvegarde le transcript de la session"),
    ("/config",            "affiche la configuration courante"),
    ("/undo",              "annule les dernières modifications appliquées par le coding agent"),
    ("/mode <ask|auto>",   "mode d'édition — ask (valide fichier par fichier) ou auto (écrit sans confirmation)"),
    ("/branch",            "fork le thread actuel pour explorer une autre piste"),
    ("/debug",             "active/désactive le mode debug"),
    ("/dump",              "affiche tous les messages du thread"),
    ("q / exit",           "quitte Axon"),
    ("Ctrl+T",             "bascule le mode plan — l'IA planifie sans écrire"),
    ("Ctrl+O",             "attacher un fichier  (= /attach)"),
    ("Ctrl+P",             "coller une image     (= /paste)"),
    ("@fichier",           "injecte un fichier dans ton message — autocomplété par Tab"),
]


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
    "minimax-m2.5:cloud",
    "glm-4.7:cloud",
    "gemma4:31b-cloud",
    "qwen3-coder-next:cloud",
    "qwen3.5:cloud",
    "qwen3-next:80b-cloud",
    "kimi-k2:1t-cloud"
]
_GEMINI_MODELS   = [
    "gemini-2.0-flash",        # rapide, gratuit — recommandé
    "gemini-2.5-flash",        # plus capable, gratuit
    "gemini-2.5-pro",          # meilleur, quota limité
    "gemini-1.5-flash",        # fallback stable
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
    return _get_ollama_local_models()


def _current_model(settings) -> str:
    if settings.llm_backend == "groq":
        return settings.groq_model
    if settings.llm_backend == "ollama_cloud":
        return settings.ollama_cloud_model
    if settings.llm_backend == "gemini":
        return settings.gemini_model
    return settings.ollama_model


def _set_model(settings, model: str) -> None:
    if settings.llm_backend == "groq":
        settings.groq_model = model
    elif settings.llm_backend == "ollama_cloud":
        settings.ollama_cloud_model = model
    elif settings.llm_backend == "gemini":
        settings.gemini_model = model
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

        # Affiche les derniers messages du thread repris
        if console:
            console.print()
            console.print(Rule("reprise de session", characters="·", style="dim color(214)"))
            msgs = get_recent_messages(chosen, n=6)
            _ROLE_STYLE = {
                "human": ("bold color(214)", "›"),
                "ai":    ("dim white",       "·"),
                "tool":  ("dim",             "⚙"),
            }
            from rich.text import Text
            for m in msgs:
                role, content = m["role"], m["content"].strip()
                if not content:
                    continue
                style, icon = _ROLE_STYLE.get(role, ("dim", "?"))
                t = Text()
                t.append(f"  {icon}  ", style="bold color(214)")
                t.append(content, style=style)
                console.print(t)
            console.print()

        return command_panel(f"thread repris : {chosen[:8]}")

    return command_panel(f"déjà sur ce thread : {chosen[:8]}")


def handle_slash(cmd: str, state: dict, cfg: SessionConfig, graph=None, console=None):
    cmd = cmd.strip()

    if cmd == "/clear":
        if console:
            console.clear()
            console.print(banner())
        return None

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
        from src.infra.checkpoint import save_last_thread
        save_last_thread(cfg.thread_id)
        return command_panel(f"nouveau thread : {cfg.thread_id}")

    if cmd == "/history":
        return _handle_history(cfg, state, console)

    if cmd.startswith("/backend"):
        from src.infra.settings import settings
        from src.ui.picker import pick
        _BACKENDS = ["groq", "ollama", "ollama_cloud", "gemini"]
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
            return command_panel("backend invalide. options : groq · ollama · ollama_cloud · gemini", error=True)
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
        from src.infra.checkpoint import save_last_thread
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
        return command_panel(f"branche créée : {old_thread[:8]} → {new_thread}")

    if cmd == "/undo":
        from src.agents.coding.pending import snapshots
        from rich.text import Text
        from rich.rule import Rule
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

    return None
