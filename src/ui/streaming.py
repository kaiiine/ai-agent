import time
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

console = Console()

def stream_once(graph, state: dict, cfg: SessionConfig) -> None:
    console.print(Rule(style="dim"))
    user_message = Prompt.ask("[bold blue]Vous[/bold blue]", console=console).strip()
    if not user_message:
        return

    # Quitter
    if user_message.lower() in {"quit", "exit", "q"}:
        raise KeyboardInterrupt

    # Slash-commands
    if user_message.startswith("/"):
        from .commands import handle_slash
        out_panel = handle_slash(user_message, state, cfg)
        if out_panel:
            console.print(out_panel)
        return

    # Langue
    user_lang = cfg.lang_pref if cfg.lang_pref in {"fr", "en"} else detect_lang(user_message)
    enforce_lang_ephemeral_system(state, user_lang)

    # Ajoute le message user
    state["messages"].append({"role": "user", "content": user_message})

    # Config LangGraph
    config = {"configurable": {"thread_id": cfg.thread_id}}

    console.print("[bold green]🤔 L'agent réfléchit...[/]")
    agent_panel = live_panel_initial()

    try:
        from rich.live import Live
        with Live(agent_panel, console=console, refresh_per_second=20) as live:
            response_content = ""
            saw_any_token = False
            deb = {"DEBOUNCE": 0.03, "last_update": 0.0}
            t0 = perf_counter()

            for msg, meta in graph.stream(state, config=config, stream_mode="messages"):
                node = meta.get("langgraph_node") or "unknown"

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
                # Fallback
                final_state = graph.invoke(state, config=config)
                last = final_state["messages"][-1]
                response_text = last["content"] if isinstance(last, dict) else getattr(last, "content", "")
                response_text = enforce_lang_output(response_text, user_lang)
                finalize_live(live, response_text, footer)
                state["messages"].append({"role": "assistant", "content": response_text})

    except Exception as e:
        console.print(Panel(f"[bold red]❌ Erreur : {e}[/bold red]", border_style="red", title="Erreur"))
