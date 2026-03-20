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
    ("/help",              "affiche cette liste de commandes"),
    ("/model <nom>",       "change le modèle LLM"),
    ("/temp <val>",        "change la température (ex: /temp 0.7)"),
    ("/lang <fr|en>",      "force la langue de réponse"),
    ("/save",              "sauvegarde le transcript de la session"),
    ("/config",            "affiche la configuration courante"),
    ("/debug",             "active/désactive le mode debug"),
    ("/dump",              "affiche tous les messages du thread"),
    ("q / exit",           "quitte Axon"),
]


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
        return command_panel(f"nouveau thread : {cfg.thread_id}")

    if cmd.startswith("/model "):
        cfg.model = cmd.split(" ", 1)[1].strip()
        return command_panel(f"modèle : {cfg.model}")

    if cmd.startswith("/temp "):
        try:
            cfg.temp = float(cmd.split(" ", 1)[1])
            return command_panel(f"température : {cfg.temp}")
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
