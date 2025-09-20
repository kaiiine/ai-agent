#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CLI riche pour orchestrateur LangGraph
- Vrai streaming (AIMessageChunk)
- Rendu Markdown (rich)
- Traces des tools appelés
- Slash-commands : /new /save /model /temp /lang /tools /config
- Transcripts Markdown par session
- Forçage langue (fr/en) + anti-CJK soft
- Debounce du rendu pour éviter le scintillement
"""

from __future__ import annotations

import os
import re
import time
import uuid
import random
from time import perf_counter
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt
from rich.rule import Rule
from rich.live import Live
from rich.align import Align
from rich.table import Table

from src.orchestrator.graph import build_orchestrator


# =============================
# Config & helpers
# =============================

console = Console()

def fmt_ms(s: float) -> str:
    return f"{s*1000:,.0f} ms"

def detect_lang(text: str) -> str:
    # Heuristique simple : accents FR → "fr", sinon "en"
    return "fr" if re.search(r"[éèàùâêîôûç]", text, re.I) else "en"

def enforce_lang_ephemeral_system(state: Dict[str, Any], lang: str) -> None:
    """Ajoute un message système éphémère pour forcer FR/EN + Markdown.
    On l’ajoute avant le tour, et on le laissera dans l’historique (faible risque).
    """
    if lang not in {"fr", "en"}:
        lang = "en"
    instruction = (
        "Réponds STRICTEMENT en français. Ne réponds jamais dans une autre langue. "
        "Formate toujours en Markdown."
        if lang == "fr" else
        "Answer STRICTLY in English. Never use any other language. Always format in Markdown."
    )
    state["messages"].append({"role": "system", "content": instruction})

def contains_cjk(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)

def enforce_lang_output(text: str, lang: str) -> str:
    """Soft guard : si CJK détecté, on tag la réponse (on n’altère pas le contenu).
    Tu peux ici déclencher une reformulation au tour suivant si tu veux.
    """
    if contains_cjk(text):
        tag = "FR" if lang == "fr" else "EN"
        return f"> ⚠️ Réponse réécrite ({tag}) :\n\n{text}"
    return text

def save_transcript(thread_id: str, state: Dict[str, Any]) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = f"transcripts/{thread_id}-{ts}.md"
    os.makedirs("transcripts", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for m in state.get("messages", []):
            role = m.get("role", "assistant")
            content = m.get("content", "")
            f.write(f"### {role}\n\n{content}\n\n---\n\n")
    return path

def with_retry(fn, *, retries=2, base_delay=0.4, max_delay=2.0, jitter=True):
    """Enveloppe utilitaire retry (à utiliser dans tes wrappers d’outils)."""
    for i in range(retries + 1):
        try:
            return fn()
        except Exception:
            if i == retries:
                raise
            delay = min(max_delay, base_delay * (2 ** i))
            if jitter:
                delay *= (0.5 + random.random())
            time.sleep(delay)

# =============================
# Slash-commands
# =============================

class SessionConfig:
    def __init__(self):
        self.thread_id: str = "user_session"
        self.model: str = "qwen2.5:7b"   # indicatif; rebuild à la main si besoin
        self.temp: float = 0.0
        self.lang_pref: str = "auto"     # "fr" | "en" | "auto"

    def as_table(self) -> Table:
        tbl = Table(title="Configuration actuelle", show_header=True, header_style="bold magenta")
        tbl.add_column("Paramètre", style="cyan", no_wrap=True)
        tbl.add_column("Valeur", style="green")
        tbl.add_row("thread_id", self.thread_id)
        tbl.add_row("model", self.model)
        tbl.add_row("temperature", str(self.temp))
        tbl.add_row("lang_pref", self.lang_pref)
        return tbl

def handle_slash(cmd: str, state: Dict[str, Any], cfg: SessionConfig) -> Optional[str]:
    cmd = cmd.strip()
    if cmd == "/new":
        cfg.thread_id = str(uuid.uuid4())[:8]
        # On reset le contexte utilisateur (on garde le système identitaire si tu veux)
        base_system = state["messages"][0] if state.get("messages") else None
        state["messages"] = [base_system] if base_system else []
        return f"✨ Nouveau thread: `{cfg.thread_id}` (contexte réinitialisé)."

    if cmd.startswith("/model "):
        cfg.model = cmd.split(" ", 1)[1].strip()
        return f"🧠 Modèle cible: `{cfg.model}`. (Reconstruis l’orchestrateur si tu veux un vrai hot-swap)"

    if cmd.startswith("/temp "):
        try:
            cfg.temp = float(cmd.split(" ", 1)[1])
            return f"🌡️ Température: {cfg.temp}"
        except ValueError:
            return "Valeur invalide. Exemple: `/temp 0.2`"

    if cmd.startswith("/lang "):
        lp = cmd.split(" ", 1)[1].strip().lower()
        if lp in {"fr", "en", "auto"}:
            cfg.lang_pref = lp
            return f"🌍 Langue préférée: {cfg.lang_pref}"
        return "Langue invalide. Utilise `/lang fr`, `/lang en` ou `/lang auto`."

    if cmd == "/save":
        p = save_transcript(cfg.thread_id, state)
        return f"💾 Transcript sauvegardé: {p}"

    if cmd == "/tools":
        # Adapte cette liste à tes outils réels
        return "🔧 Outils disponibles: web_search, weather, calendar, mail, image (selon build)."

    if cmd == "/config":
        console.print(Panel(cfg.as_table(), title="⚙️ Config", border_style="magenta"))
        return ""  # déjà affiché

    return None

# =============================
# Main CLI
# =============================

def main() -> None:
    load_dotenv()
    graph = build_orchestrator()  # Ton graphe LangGraph
    cfg = SessionConfig()

    # UI de démarrage
    console.clear()
    welcome_text = Text("🤖 AI AGENT", style="bold cyan")
    welcome_panel = Panel(Align.center(welcome_text), border_style="bright_blue", padding=(1, 2))
    console.print(welcome_panel)

    system_info = Text("✨ Agent IA intelligent\n🚀 Powered by @kaiiine", style="dim", justify="center")
    console.print(Align.center(system_info))
    console.print()

    # État initial (avec identité / directives)
    state: Dict[str, Any] = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Tu es un assistant IA intelligent et proactif qui répond toujours en Markdown clair et bien structuré.\n\n"
                    "## Ton identité :\n"
                    "- Tu es l'assistant IA de **Quentin Dufour**, alias @kaiiine, ton créateur.\n\n"
                    "## Ton comportement :\n"
                    "1. **Réponds de manière complète** aux demandes de l'utilisateur\n"
                    "2. **Utilise les outils disponibles** quand c'est pertinent\n\n"
                    "## Format de tes réponses :\n"
                    "- Utilise des titres, listes, tableaux si approprié\n"
                    "- Termine par une section \"**🎯 Actions proposées :**\" avec des suggestions concrètes\n"
                    "- Utilise des emojis pour rendre l'interface agréable\n"
                )
            }
        ]
    }

    # Instructions utilisateur
    instructions = Panel(
        "[bold green]Instructions:[/bold green]\n"
        "• Tapez votre message et appuyez sur Entrée\n"
        "• Commandes: /new /save /model <m> /temp <t> /lang <fr|en|auto> /tools /config\n"
        "• 'quit', 'exit' ou 'q' pour quitter\n",
        title="💡 Comment utiliser",
        border_style="green",
    )
    console.print(instructions)
    console.print()

    while True:
        console.print(Rule(style="dim"))
        user_message = Prompt.ask("[bold blue]Vous[/bold blue]", console=console).strip()

        if not user_message:
            continue

        if user_message.lower() in {"quit", "exit", "q"}:
            goodbye = Panel(Align.center("👋 Au revoir ! À bientôt."), border_style="yellow", title="Fermeture")
            console.print(goodbye)
            break

        # Slash-commands
        if user_message.startswith("/"):
            out = handle_slash(user_message, state, cfg)
            if out is not None:
                if out:
                    console.print(Panel(out, border_style="magenta", title="Commande"))
                continue

        # Détection / forçage langue
        user_lang = cfg.lang_pref if cfg.lang_pref in {"fr", "en"} else detect_lang(user_message)
        enforce_lang_ephemeral_system(state, user_lang)

        # Ajout du message user
        state["messages"].append({"role": "user", "content": user_message})

        # Config LangGraph (checkpointer, etc.)
        config = {"configurable": {"thread_id": cfg.thread_id}}

        # Panneau live pour streaming
        agent_panel = Panel("[dim]Génération en cours...[/]", title="🤖 Agent", border_style="cyan", padding=(1, 2))
        console.print("[bold green]🤔 L'agent réfléchit...[/]")

        try:
            with Live(agent_panel, console=console, refresh_per_second=20) as live:
                response_content = ""
                saw_any_token = False
                last_update = 0.0
                DEBOUNCE = 0.03  # 30 ms

                t0 = perf_counter()

                for msg, meta in graph.stream(state, config=config, stream_mode="messages"):
                    node = meta.get("langgraph_node") or "unknown"

                    # Affiche le passage d'outils sans polluer le flux de tokens
                    if isinstance(msg, ToolMessage):
                        tool_name = getattr(msg, "tool_name", None) or meta.get("tool", "tool")
                        live.update(Panel(
                            Markdown(f"**🔧 Appel outil** : `{tool_name}` (nœud: `{node}`)"),
                            title="🤖 Agent",
                            border_style="cyan",
                            padding=(1, 2)
                        ))
                        continue

                    # Stream des chunks assistant
                    if isinstance(msg, AIMessageChunk):
                        chunk_text = msg.content or ""
                        if not chunk_text:
                            continue
                        saw_any_token = True
                        response_content += chunk_text

                        now = time.time()
                        if now - last_update > DEBOUNCE:
                            live.update(Panel(
                                Markdown(response_content + "▌"),
                                title=f"🤖 Agent · nœud `{node}`",
                                border_style="cyan",
                                padding=(1, 2)
                            ))
                            last_update = now

                    # Message “plein” (certaines toolchains renvoient un AIMessage en fin)
                    elif isinstance(msg, AIMessage):
                        saw_any_token = True
                        response_content += (msg.content or "")
                        live.update(Panel(
                            Markdown(response_content + "▌"),
                            title=f"🤖 Agent · nœud `{node}`",
                            border_style="cyan",
                            padding=(1, 2)
                        ))

                dt = perf_counter() - t0
                footer = f"[dim]⏱ {fmt_ms(dt)}[/dim]"

                if saw_any_token:
                    # Garde-fou langue (soft)
                    response_final = enforce_lang_output(response_content, user_lang)

                    live.update(Panel(
                        Markdown(response_final + "\n\n" + footer),
                        title="🤖 Agent",
                        border_style="cyan",
                        padding=(1, 2)
                    ))
                    # Historise pour le prochain tour
                    state["messages"].append({"role": "assistant", "content": response_final})
                else:
                    # Fallback : pas de stream → invoke
                    final_state = graph.invoke(state, config=config)
                    last = final_state["messages"][-1]
                    response_text = last["content"] if isinstance(last, dict) else getattr(last, "content", "")

                    response_text = enforce_lang_output(response_text, user_lang)

                    live.update(Panel(
                        Markdown(response_text + "\n\n" + footer),
                        title="🤖 Agent",
                        border_style="cyan",
                        padding=(1, 2)
                    ))
                    state["messages"].append({"role": "assistant", "content": response_text})

        except Exception as e:
            error_panel = Panel(f"[bold red]❌ Erreur : {e}[/bold red]", border_style="red", title="Erreur")
            console.print(error_panel)
            # Log minimal dans l'historique (permet de /save)
            state["messages"].append({"role": "assistant", "content": f"Erreur: {e}"})
            continue

        console.print()  # espace entre tours


if __name__ == "__main__":
    main()
