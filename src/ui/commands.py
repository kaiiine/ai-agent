import uuid
import json
from rich.panel import Panel
from rich.pretty import Pretty
from .panels import config_table
from .transcript import save_transcript
from .config import SessionConfig

# État global du mode debug
debug_state = {"enabled": False}

def handle_slash(cmd: str, state: dict, cfg: SessionConfig):
    cmd = cmd.strip()

    if cmd == "/new":
        cfg.thread_id = str(uuid.uuid4())[:8]
        base_system = state["messages"][0] if state.get("messages") else None
        state["messages"] = [base_system] if base_system else []
        return Panel(f"✨ Nouveau thread: `{cfg.thread_id}` (contexte réinitialisé).", border_style="magenta", title="Commande")

    if cmd.startswith("/model "):
        cfg.model = cmd.split(" ", 1)[1].strip()
        return Panel(f"🧠 Modèle cible: `{cfg.model}`", border_style="magenta", title="Commande")

    if cmd.startswith("/temp "):
        try:
            cfg.temp = float(cmd.split(" ", 1)[1])
            return Panel(f"🌡️ Température: {cfg.temp}", border_style="magenta", title="Commande")
        except ValueError:
            return Panel("Valeur invalide. Exemple: `/temp 0.2`", border_style="red", title="Erreur")

    if cmd.startswith("/lang "):
        lp = cmd.split(" ", 1)[1].strip().lower()
        if lp in {"fr", "en", "auto"}:
            cfg.lang_pref = lp
            return Panel(f"🌍 Langue préférée: {cfg.lang_pref}", border_style="magenta", title="Commande")
        return Panel("Langue invalide. Utilise `/lang fr`, `/lang en` ou `/lang auto`.", border_style="red", title="Erreur")

    if cmd == "/save":
        p = save_transcript(cfg.thread_id, state)
        return Panel(f"💾 Transcript sauvegardé: {p}", border_style="magenta", title="Commande")

    if cmd == "/tools":
        return Panel("🔧 Outils: web_search, weather, calendar, mail, image (selon build).", border_style="magenta", title="Commande")

    if cmd == "/config":
        return Panel(config_table(cfg), title="⚙️ Config", border_style="magenta")

    if cmd == "/debug":
        debug_state["enabled"] = not debug_state["enabled"]
        status = "ON" if debug_state["enabled"] else "OFF"
        return Panel(f"🐛 Mode debug: {status}", border_style="yellow", title="Commande")

    if cmd == "/dump":
        formatted = Pretty(state["messages"], expand_all=True)
        return Panel(formatted, title="🗂️ Dump complet de l'historique", border_style="cyan")
    
    if cmd == "/deepth_search":
        cfg.depth_search = not cfg.depth_search
        status = "activée" if cfg.depth_search else "désactivée"
        return Panel(f"🔎 Depth Search {status}.", border_style="magenta", title="Commande")

    return None
