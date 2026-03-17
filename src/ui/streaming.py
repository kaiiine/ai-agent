import json
import threading
from time import perf_counter

from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage
from rich.live import Live
from rich.rule import Rule
from rich.panel import Panel
from rich.pretty import Pretty
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from .config import fmt_ms, SessionConfig
from .language import detect_lang, enforce_lang_output
from .panels import live_panel_initial, tool_call_panel, command_panel
from .render import update_live_markdown, finalize_live
from .commands import debug_state

console = Console()

_pt_style = Style.from_dict({
    "axon": f"bold ansiyellow",
    "sep":  "ansiyellow",
})
_session: PromptSession = PromptSession(
    history=InMemoryHistory(),
    style=_pt_style,
    mouse_support=False,
)


def _debug_prompt(state: dict, graph, cfg: SessionConfig):
    try:
        from src.llm.prompts import SYSTEM_PROMPT
        from src.utils.tools import get_tool_names

        config = {"configurable": {"thread_id": cfg.thread_id}}
        snapshot = graph.get_state(config)
        messages = snapshot.values.get("messages", []) if snapshot.values else state.get("messages", [])

        parts = [f"[dim]system:[/dim] {SYSTEM_PROMPT.format(tools_available=get_tool_names())[:300]}..."]
        for m in messages:
            content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
            role = m.get("role", "?") if isinstance(m, dict) else getattr(m, "type", "?")
            parts.append(f"[dim]{role}:[/dim] {content[:200]}")

        console.print(Panel("\n\n".join(parts), box=__import__("rich.box", fromlist=["SIMPLE_HEAD"]).SIMPLE_HEAD, border_style="dim", title="prompt"))
    except Exception as e:
        console.print(f"[dim]debug error: {e}[/dim]")


def stream_once(graph, state: dict, cfg: SessionConfig) -> None:
    console.print(Rule(characters="·", style="dim color(214)"))
    try:
        user_message = _session.prompt("› ").strip()
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt
    if not user_message:
        return

    if user_message.lower() in {"quit", "exit", "q"}:
        raise KeyboardInterrupt

    if user_message.startswith("/"):
        from .commands import handle_slash
        result = handle_slash(user_message, state, cfg, graph, console)
        if result:
            console.print(result)
        return

    cfg.debug = debug_state["enabled"]
    user_lang = cfg.lang_pref if cfg.lang_pref in {"fr", "en"} else detect_lang(user_message)
    current_state = {"messages": [{"role": "user", "content": user_message}]}
    config = {"configurable": {"thread_id": cfg.thread_id}}

    if cfg.debug:
        _debug_prompt(state, graph, cfg)

    stop_thinking = threading.Event()

    def _thinking_loop(live):
        i = 0
        while not stop_thinking.is_set():
            live.update(live_panel_initial(i % 4))
            i += 1
            stop_thinking.wait(0.4)

    try:
        with Live(live_panel_initial(), console=console, refresh_per_second=20, vertical_overflow="visible") as live:
            response_content = ""
            saw_any_token = False
            deb = {"DEBOUNCE": 0.03, "last_update": 0.0}
            t0 = perf_counter()

            t = threading.Thread(target=_thinking_loop, args=(live,), daemon=True)
            t.start()

            for msg, meta in graph.stream(current_state, config=config, stream_mode="messages"):
                node = meta.get("langgraph_node") or "unknown"

                if cfg.debug:
                    console.print(f"[dim]node={node}[/dim]")

                if isinstance(msg, ToolMessage):
                    tool_name = getattr(msg, "tool_name", None) or meta.get("tool", "tool")
                    live.update(tool_call_panel(tool_name))
                    if cfg.debug:
                        live.console.print(Panel(
                            Pretty(msg.content),
                            title=f"[dim]{tool_name}[/dim]",
                            border_style="dim",
                        ))
                    continue

                if isinstance(msg, (AIMessageChunk, AIMessage)):
                    chunk_text = msg.content or ""
                    if not chunk_text:
                        continue
                    stop_thinking.set()
                    saw_any_token = True
                    response_content += chunk_text
                    update_live_markdown(live, response_content, deb, cursor=True)

            footer = fmt_ms(perf_counter() - t0)

            if saw_any_token:
                finalize_live(live, enforce_lang_output(response_content, user_lang), footer)
            else:
                final_state = graph.invoke(current_state, config=config)
                last = final_state["messages"][-1]
                text = last["content"] if isinstance(last, dict) else getattr(last, "content", "")
                finalize_live(live, enforce_lang_output(text, user_lang), footer)

    except Exception as e:
        console.print(command_panel(f"erreur : {e}", error=True))
