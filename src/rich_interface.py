"""
Interface Rich moderne pour l'agent IA avec indicateurs visuels par agent.
"""
import asyncio
import threading
import time
from typing import Dict, Any, Optional
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.columns import Columns
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.align import Align
from rich.box import ROUNDED
from rich import print as rprint

from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage

from src.orchestrator.graph import build_orchestrator


class RichAgentInterface:
    """Interface Rich moderne pour l'agent IA"""
    
    # Couleurs et thèmes par agent
    AGENT_THEMES = {
        "search": {
            "color": "cyan",
            "icon": "🔍",
            "name": "Search Agent",
            "description": "Recherche d'informations"
        },
        "weather": {
            "color": "blue",
            "icon": "🌤️",
            "name": "Weather Agent", 
            "description": "Météorologie"
        },
        "chatbot": {
            "color": "green",
            "icon": "💬",
            "name": "Chat Agent",
            "description": "Conversation générale"
        },
        "tools": {
            "color": "yellow",
            "icon": "🔧",
            "name": "Tool Agent",
            "description": "Exécution d'outils"
        }
    }
    
    def __init__(self):
        self.console = Console()
        self.app = None
        self.current_agent = "chatbot"
        self.messages_history = []
        self.is_processing = False
        self.current_response = ""
        self.tool_calls_count = 0
        self.session_start = datetime.now()
        
    def initialize_app(self):
        """Initialise l'application agent"""
        load_dotenv()
        self.app = build_orchestrator()
        
    def get_agent_theme(self, agent_name: str) -> Dict[str, str]:
        """Récupère le thème pour un agent donné"""
        return self.AGENT_THEMES.get(agent_name, self.AGENT_THEMES["chatbot"])
        
    def create_header(self) -> Panel:
        """Crée l'en-tête de l'interface"""
        theme = self.get_agent_theme(self.current_agent)
        
        title = Text()
        title.append("🤖 Agent IA Assistant ", style="bold white")
        title.append(f"{theme['icon']} {theme['name']}", style=f"bold {theme['color']}")
        
        subtitle = Text()
        subtitle.append(f"Status: ", style="dim")
        if self.is_processing:
            subtitle.append("⚡ En traitement...", style=f"bold {theme['color']} blink")
        else:
            subtitle.append("✅ Prêt", style="bold green")
            
        subtitle.append(f" | Session: {self.format_duration()}", style="dim")
        subtitle.append(f" | Tools utilisés: {self.tool_calls_count}", style="dim")
        
        header_content = Align.center(
            Text.assemble(title, "\n", subtitle),
            vertical="middle"
        )
        
        return Panel(
            header_content,
            style=f"bold {theme['color']}",
            box=ROUNDED,
            height=5
        )
        
    def create_agent_status_bar(self) -> Panel:
        """Crée la barre de statut des agents"""
        columns = []
        
        for agent_key, theme in self.AGENT_THEMES.items():
            if agent_key == self.current_agent:
                status_text = Text()
                status_text.append(f"{theme['icon']} {theme['name']}", 
                                 style=f"bold {theme['color']} on white")
                status_text.append(f"\n{theme['description']}", style=f"{theme['color']}")
            else:
                status_text = Text()
                status_text.append(f"{theme['icon']} {theme['name']}", style="dim")
                status_text.append(f"\n{theme['description']}", style="dim")
                
            panel = Panel(
                Align.center(status_text, vertical="middle"),
                style=f"{theme['color']}" if agent_key == self.current_agent else "dim",
                box=ROUNDED,
                height=4
            )
            columns.append(panel)
            
        return Panel(
            Columns(columns, equal=True),
            title="🎯 Agents Disponibles",
            style="white",
            box=ROUNDED
        )
        
    def create_conversation_panel(self) -> Panel:
        """Crée le panneau de conversation"""
        if not self.messages_history and not self.current_response:
            content = Align.center(
                Text("Commencez une conversation en tapant votre message...", style="dim italic"),
                vertical="middle"
            )
        else:
            content = []
            
            # Historique des messages
            for msg in self.messages_history[-5:]:  # 5 derniers messages
                if msg["role"] == "user":
                    content.append(Text(f"👤 Vous: {msg['content']}", style="bold white"))
                else:
                    agent_theme = self.get_agent_theme(msg.get("agent", "chatbot"))
                    content.append(Text(f"{agent_theme['icon']} Assistant: {msg['content']}", 
                                      style=f"{agent_theme['color']}"))
                content.append(Text(""))  # Ligne vide
            
            # Réponse en cours
            if self.current_response:
                agent_theme = self.get_agent_theme(self.current_agent)
                content.append(Text(f"{agent_theme['icon']} Assistant: {self.current_response}", 
                                  style=f"{agent_theme['color']}"))
                
                if self.is_processing:
                    content.append(Text("▌", style=f"bold {agent_theme['color']} blink"))
                    
            # Joindre le contenu
            if content:
                content = Text("\n").join(content)
            else:
                content = Text("Aucun message", style="dim")
        
        return Panel(
            content,
            title="💬 Conversation",
            style="white",
            box=ROUNDED,
            height=15,
            scrollable=True
        )
        
    def create_input_panel(self) -> Panel:
        """Crée le panneau de saisie"""
        theme = self.get_agent_theme(self.current_agent)
        
        input_text = Text()
        input_text.append("💭 Tapez votre message ici: ", style="bold white")
        
        if self.is_processing:
            input_text.append("(En attente de réponse...)", style="dim italic")
        else:
            input_text.append("(Appuyez sur Entrée pour envoyer, 'quit' pour quitter)", style="dim")
            
        return Panel(
            input_text,
            style=f"{theme['color']}",
            box=ROUNDED,
            height=3
        )
        
    def create_main_layout(self) -> Layout:
        """Crée la mise en page principale"""
        layout = Layout()
        
        layout.split_column(
            Layout(self.create_header(), name="header", size=5),
            Layout(self.create_agent_status_bar(), name="agents", size=6),
            Layout(self.create_conversation_panel(), name="conversation"),
            Layout(self.create_input_panel(), name="input", size=3)
        )
        
        return layout
        
    def format_duration(self) -> str:
        """Formate la durée de la session"""
        duration = datetime.now() - self.session_start
        minutes = int(duration.total_seconds() / 60)
        seconds = int(duration.total_seconds() % 60)
        return f"{minutes:02d}:{seconds:02d}"
        
    def detect_agent_from_message(self, content: str) -> str:
        """Détecte l'agent probable basé sur le contenu du message"""
        content_lower = content.lower()
        
        # Mots-clés pour détection d'agent
        if any(word in content_lower for word in ["météo", "weather", "température", "temps", "climat"]):
            return "weather"
        elif any(word in content_lower for word in ["recherche", "search", "trouve", "cherche", "google"]):
            return "search"
        else:
            return "chatbot"
            
    async def process_message(self, user_input: str) -> None:
        """Traite un message utilisateur de manière asynchrone"""
        self.is_processing = True
        self.current_response = ""
        self.current_agent = self.detect_agent_from_message(user_input)
        
        # Ajouter le message utilisateur à l'historique
        self.messages_history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now()
        })
        
        try:
            state = {"messages": [{"role": "user", "content": user_input}]}
            response_content = ""
            
            for msg, meta in self.app.stream(
                state,
                stream_mode="messages",
                config={"configurable": {"thread_id": "rich_interface"}},
            ):
                # Détecter le type d'agent basé sur les métadonnées
                if meta and "langgraph_node" in meta:
                    node_name = meta["langgraph_node"]
                    if node_name in self.AGENT_THEMES:
                        self.current_agent = node_name
                
                if isinstance(msg, ToolMessage):
                    self.tool_calls_count += 1
                    self.current_agent = "tools"
                    await asyncio.sleep(0.1)  # Petite pause pour l'effet visuel
                    continue
                    
                if isinstance(msg, (AIMessageChunk, AIMessage)):
                    content = msg.content or ""
                    if content:
                        response_content += content
                        self.current_response = response_content
                        await asyncio.sleep(0.05)  # Effet de frappe
                        
        except Exception as e:
            self.current_response = f"❌ Erreur: {str(e)}"
            
        finally:
            # Ajouter la réponse à l'historique
            if self.current_response:
                self.messages_history.append({
                    "role": "assistant", 
                    "content": self.current_response,
                    "agent": self.current_agent,
                    "timestamp": datetime.now()
                })
            
            self.is_processing = False
            self.current_response = ""
            self.current_agent = "chatbot"  # Retour au mode chat par défaut
            
    def run_interface(self):
        """Lance l'interface synchrone avec Rich Live"""
        self.console.clear()
        
        # Message de bienvenue
        self.console.print("🎉 Interface Rich Agent IA initialisée!", style="bold green")
        self.console.print("Tapez votre message ci-dessous (tapez 'quit' pour quitter):\n")
        
        with Live(self.create_main_layout(), console=self.console, refresh_per_second=4) as live:
            
            while True:
                try:
                    # Mise à jour continue de l'affichage
                    live.update(self.create_main_layout())
                    
                    if not self.is_processing:
                        # Afficher le prompt en dehors du Live layout
                        live.stop()
                        theme = self.get_agent_theme(self.current_agent)
                        self.console.print(f"\n[{theme['color']}]💭 Votre message:[/{theme['color']}] ", end="")
                        
                        try:
                            user_input = input().strip()
                        except (EOFError, KeyboardInterrupt):
                            self.console.print("\n👋 Au revoir!", style="bold yellow")
                            break
                            
                        live.start()
                        
                        if user_input.lower() in {"quit", "exit", "q", "bye"}:
                            self.console.print("👋 Au revoir! Merci d'avoir utilisé l'Agent IA.", style="bold yellow")
                            break
                            
                        if user_input:
                            # Traiter le message de manière synchrone
                            asyncio.run(self.process_message(user_input))
                    else:
                        time.sleep(0.1)
                        
                except KeyboardInterrupt:
                    self.console.print("\n🛑 Interface interrompue par l'utilisateur.", style="bold red")
                    break
                    
    def run(self):
        """Point d'entrée principal de l'interface"""
        self.console.print("🚀 Initialisation de l'Agent IA...", style="bold blue")
        self.initialize_app()
        self.console.print("✅ Agent IA prêt!", style="bold green")
        
        # Lancer l'interface
        self.run_interface()


def main():
    """Point d'entrée principal"""
    interface = RichAgentInterface()
    interface.run()


if __name__ == "__main__":
    main()
