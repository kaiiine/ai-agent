import json
from time import perf_counter
from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage
from rich.live import Live
from rich.rule import Rule
from rich.prompt import Prompt
from rich.panel import Panel
from rich.console import Console

from .config import fmt_ms, SessionConfig
from .language import detect_lang, enforce_lang_ephemeral_system, enforce_lang_output
from .panels import live_panel_initial, tool_call_panel
from .render import update_live_markdown, finalize_live
from .commands import debug_state

console = Console()


def _print_prompt_debug(state: dict):
    """Affiche tout le prompt envoyé au LLM (mode debug)."""
    try:
        parts = []
        for m in state.get("messages", []):
            if isinstance(m, dict):
                parts.append(f"[bold]{m.get('role','?')}:[/bold] {m.get('content','')}")
        console.print(Panel("\n\n".join(parts), title="🧾 Prompt complet", border_style="magenta"))
    except Exception as e:
        console.print(f"[red]Erreur affichage prompt: {e}[/red]")


def _print_tool_calls_debug(msg, node: str):
    """Affiche les tool-calls émis par le LLM (mode debug)."""
    tool_calls = getattr(msg, "tool_calls", None) or []
    for tc in tool_calls:
        name = tc.get("name") or "tool"
        args = tc.get("args") or tc.get("arguments") or {}
        console.print(Panel(
            f"[bold cyan]Nom:[/bold cyan] {name}\n\n"
            f"[bold]Arguments:[/bold]\n```json\n{json.dumps(args, indent=2, ensure_ascii=False)}\n```",
            title=f"🔧 Appel d’outil (nœud: {node})",
            border_style="cyan"
        ))


def stream_once(graph, state: dict, cfg: SessionConfig) -> None:
    console.print(Rule(style="dim"))
    user_message = Prompt.ask("[bold blue]Vous[/bold blue]", console=console).strip()
    if not user_message:
        return

    if user_message.lower() in {"quit", "exit", "q"}:
        raise KeyboardInterrupt

    if user_message.startswith("/"):
        from .commands import handle_slash
        out_panel = handle_slash(user_message, state, cfg)
        if out_panel:
            console.print(out_panel)
        return

    cfg.debug = debug_state["enabled"]

    # Détection langue
    user_lang = cfg.lang_pref if cfg.lang_pref in {"fr", "en"} else detect_lang(user_message)
    enforce_lang_ephemeral_system(state, user_lang)

    # Ajout du message
    state["messages"].append({"role": "user", "content": user_message})

    # Affichage du prompt complet si debug
    if cfg.debug:
        _print_prompt_debug(state)

    config = {"configurable": {"thread_id": cfg.thread_id}}

    console.print("[bold green]🤔 L'agent réfléchit...[/]")
    agent_panel = live_panel_initial()

    try:
        with Live(agent_panel, console=console, refresh_per_second=20) as live:
            response_content = ""
            saw_any_token = False
            deb = {"DEBOUNCE": 0.03, "last_update": 0.0}
            t0 = perf_counter()

            for msg, meta in graph.stream(state, config=config, stream_mode="messages"):
                node = meta.get("langgraph_node") or "unknown"

                if cfg.debug:
                    console.print(f"[dim]node={node} run_id={meta.get('run_id')}[/dim]")
                    _print_tool_calls_debug(msg, node)

                if isinstance(msg, ToolMessage):
                    tool_name = getattr(msg, "tool_name", None) or meta.get("tool", "tool")
                    live.update(tool_call_panel(tool_name, node))
                    continue

                if isinstance(msg, AIMessageChunk):
                    chunk_text = msg.content or ""
                    if not chunk_text:
                        continue
                    saw_any_token = True
                    response_content += chunk_text
                    update_live_markdown(live, response_content, node, deb, cursor=True)

                elif isinstance(msg, AIMessage):
                    saw_any_token = True
                    response_content += (msg.content or "")
                    update_live_markdown(live, response_content, node, deb, cursor=True)

            footer = f"[dim]⏱ {fmt_ms(perf_counter() - t0)}[/dim]"

            if saw_any_token:
                response_final = enforce_lang_output(response_content, user_lang)
                finalize_live(live, response_final, footer)
                state["messages"].append({"role": "assistant", "content": response_final})
            else:
                final_state = graph.invoke(state, config=config)
                last = final_state["messages"][-1]
                response_text = last["content"] if isinstance(last, dict) else getattr(last, "content", "")
                response_text = enforce_lang_output(response_text, user_lang)
                finalize_live(live, response_text, footer)
                state["messages"].append({"role": "assistant", "content": response_text})

    except Exception as e:
        console.print(Panel(f"[bold red]❌ Erreur : {e}[/bold red]", border_style="red", title="Erreur"))
