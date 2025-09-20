from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.table import Table

from .config import SessionConfig

console = Console()

def banner():
    welcome_text = Text("🤖 AI AGENT", style="bold cyan")
    return Panel(Align.center(welcome_text), border_style="bright_blue", padding=(1, 2))

def system_info():
    return Align.center(Text("✨ Agent IA intelligent\n🚀 Powered by @kaiiine",
                             style="dim", justify="center"))

def instructions():
    return Panel(
        "[bold green]Instructions:[/bold green]\n"
        "• Tapez votre message et Entrée\n"
        "• Commandes: /new /save /model <m> /temp <t> /lang <fr|en|auto> /tools /config\n"
        "• 'quit', 'exit' ou 'q' pour quitter\n",
        title="💡 Comment utiliser",
        border_style="green",
    )

def live_panel_initial():
    return Panel("[dim]Génération en cours...[/]", title="🤖 Agent", border_style="cyan", padding=(1, 2))

def tool_call_panel(tool_name: str, node: str):
    from rich.markdown import Markdown
    return Panel(Markdown(f"**🔧 Appel outil** : `{tool_name}` (nœud: `{node}`)"),
                 title="🤖 Agent", border_style="cyan", padding=(1, 2))

def final_panel(md_text: str, title: str = "🤖 Agent"):
    from rich.markdown import Markdown
    return Panel(Markdown(md_text), title=title, border_style="cyan", padding=(1, 2))

def config_table(cfg: SessionConfig) -> Table:
    tbl = Table(title="Configuration actuelle", show_header=True, header_style="bold magenta")
    tbl.add_column("Paramètre", style="cyan", no_wrap=True)
    tbl.add_column("Valeur", style="green")
    tbl.add_row("thread_id", cfg.thread_id)
    tbl.add_row("model", cfg.model)
    tbl.add_row("temperature", str(cfg.temp))
    tbl.add_row("lang_pref", cfg.lang_pref)
    return tbl
