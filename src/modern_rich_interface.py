"""
Interface Rich moderne et robuste pour l'agent IA
Version simplifiée pour éviter les problèmes d'asyncio
"""
import time
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime
from queue import Queue, Empty

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.columns import Columns
from rich.align import Align
from rich.box import ROUNDED, SIMPLE
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.padding import Padding

from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage

# Import relatif sécurisé
try:
    from src.orchestrator.graph import build_orchestrator
except ImportError:
    # Fallback si les imports ne fonctionnent pas
    def build_orchestrator():
        return None


class ModernAgentInterface:
    """Interface Rich moderne pour l'agent IA avec threading"""
    
    # Configuration des agents avec couleurs et icônes
    AGENT_CONFIG = {
        "search": {
            "color": "bright_cyan",
            "icon": "🔍",
            "name": "Search Agent",
            "desc": "Recherche web"
        },
        "weather": {
            "color": "bright_blue", 
            "icon": "🌤️",
            "name": "Weather Agent",
            "desc": "Informations météo"
        },
        "chatbot": {
            "color": "bright_green",
            "icon": "💬", 
            "name": "Chat Agent",
            "desc": "Conversation générale"
        },
        "tools": {
            "color": "bright_yellow",
            "icon": "🔧",
            "name": "Tool Executor", 
            "desc": "Exécution d'outils"
        }
    }
    
    def __init__(self):
        self.console = Console()
        self.app = None
        self.current_agent = "chatbot"
        self.conversation_history = []
        self.is_processing = False
        self.current_message = ""
        self.tools_used = 0
        self.session_start = datetime.now()
        self.message_queue = Queue()
        
    def init_agent(self):
        """Initialise l'application agent"""
        try:
            load_dotenv()
            self.app = build_orchestrator()
            return True
        except Exception as e:
            self.console.print(f"❌ Erreur d'initialisation: {e}", style="bold red")
            return False
            
    def get_agent_config(self, agent_name: str) -> Dict[str, str]:
        """Récupère la configuration d'un agent"""
        return self.AGENT_CONFIG.get(agent_name, self.AGENT_CONFIG["chatbot"])
        
    def detect_agent_type(self, message: str) -> str:
        """Détecte le type d'agent basé sur le message"""
        msg_lower = message.lower()
        
        weather_keywords = ["météo", "weather", "température", "temps", "climat", "pluie", "soleil"]
        search_keywords = ["recherche", "search", "trouve", "cherche", "google", "internet"]
        
        if any(kw in msg_lower for kw in weather_keywords):
            return "weather"
        elif any(kw in msg_lower for kw in search_keywords):
            return "search" 
        else:
            return "chatbot"
            
    def create_header_panel(self) -> Panel:
        """Crée le panneau d'en-tête avec info de session"""
        config = self.get_agent_config(self.current_agent)
        
        # Titre principal
        title = Text()
        title.append("🤖 Agent IA Assistant ", style="bold white")
        title.append(f"{config['icon']} {config['name']}", style=f"bold {config['color']}")
        
        # Ligne de statut
        status_line = Text()
        if self.is_processing:
            status_line.append("⚡ Processing", style=f"bold {config['color']} blink")
        else:
            status_line.append("✅ Ready", style="bold green")
            
        # Informations de session 
        duration = datetime.now() - self.session_start
        mins, secs = divmod(int(duration.total_seconds()), 60)
        
        status_line.append(f" │ Session: {mins:02d}:{secs:02d}", style="dim white")
        status_line.append(f" │ Tools: {self.tools_used}", style="dim white")
        status_line.append(f" │ Messages: {len(self.conversation_history)}", style="dim white")
        
        content = Text.assemble(title, "\n", status_line)
        
        return Panel(
            Align.center(content, vertical="middle"),
            style=f"bold {config['color']}",
            box=ROUNDED,
            height=4
        )
        
    def create_agents_panel(self) -> Panel:
        """Crée le panneau des agents disponibles"""
        agent_panels = []
        
        for agent_key, config in self.AGENT_CONFIG.items():
            # Style selon l'agent actuel
            if agent_key == self.current_agent:
                style = f"bold {config['color']}"
                text_style = f"bold {config['color']} on white"
                desc_style = f"{config['color']}"
            else:
                style = "dim"
                text_style = "dim"
                desc_style = "dim"
                
            # Contenu de l'agent
            agent_text = Text()
            agent_text.append(f"{config['icon']} {config['name']}", style=text_style)
            agent_text.append(f"\n{config['desc']}", style=desc_style)
            
            panel = Panel(
                Align.center(agent_text, vertical="middle"),
                style=style,
                box=SIMPLE,
                height=3
            )
            agent_panels.append(panel)
            
        return Panel(
            Columns(agent_panels, equal=True, expand=True),
            title="🎯 Available Agents",
            style="white",
            box=ROUNDED
        )
        
    def create_conversation_panel(self) -> Panel:
        """Crée le panneau de conversation"""
        if not self.conversation_history and not self.current_message:
            content = Align.center(
                Text("🚀 Prêt à converser! Tapez votre message ci-dessous.", 
                     style="dim italic"),
                vertical="middle"
            )
        else:
            lines = []
            
            # Afficher les 8 derniers messages
            recent_messages = self.conversation_history[-8:]
            
            for msg in recent_messages:
                if msg["role"] == "user":
                    lines.append(Text(f"👤 Vous: {msg['content']}", style="bold white"))
                else:
                    agent_config = self.get_agent_config(msg.get("agent", "chatbot"))
                    lines.append(Text(f"{agent_config['icon']} Assistant: {msg['content']}", 
                                    style=agent_config['color']))
                lines.append(Text())  # Ligne vide
                
            # Message en cours de traitement
            if self.current_message:
                config = self.get_agent_config(self.current_agent)
                lines.append(Text(f"{config['icon']} Assistant: {self.current_message}", 
                                style=config['color']))
                
                if self.is_processing:
                    lines.append(Text("▋", style=f"bold {config['color']} blink"))
                    
            content = Text("\n").join(lines) if lines else Text("Aucun message", style="dim")
            
        return Panel(
            content,
            title="💬 Conversation",
            style="white", 
            box=ROUNDED,
            padding=(1, 2)
        )
        
    def create_input_panel(self) -> Panel:
        """Crée le panneau d'entrée"""
        config = self.get_agent_config(self.current_agent)
        
        if self.is_processing:
            text = Text("⏳ En attente de réponse...", style="dim italic")
        else:
            text = Text()
            text.append("💭 Tapez votre message: ", style="bold white")
            text.append("(Enter=Envoyer, 'quit'=Quitter)", style="dim")
            
        return Panel(
            text,
            style=config['color'],
            box=ROUNDED,
            height=3
        )
        
    def create_main_layout(self) -> Layout:
        """Crée la mise en page principale"""
        layout = Layout()
        
        layout.split_column(
            Layout(self.create_header_panel(), name="header", size=4),
            Layout(self.create_agents_panel(), name="agents", size=5), 
            Layout(self.create_conversation_panel(), name="conversation"),
            Layout(self.create_input_panel(), name="input", size=3)
        )
        
        return layout
        
    def process_agent_message(self, user_input: str) -> None:
        """Traite un message via l'agent (dans un thread séparé)"""
        self.is_processing = True
        self.current_message = ""
        self.current_agent = self.detect_agent_type(user_input)
        
        # Ajouter le message utilisateur
        self.conversation_history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now()
        })
        
        try:
            if self.app is None:
                self.current_message = "❌ Agent non initialisé"
                return
                
            state = {"messages": [{"role": "user", "content": user_input}]}
            response_content = ""
            
            for msg, meta in self.app.stream(
                state,
                stream_mode="messages", 
                config={"configurable": {"thread_id": "rich_session"}},
            ):
                # Détecter l'agent selon les métadonnées
                if meta and "langgraph_node" in meta:
                    node_name = meta["langgraph_node"]
                    if node_name in self.AGENT_CONFIG:
                        self.current_agent = node_name
                        
                if isinstance(msg, ToolMessage):
                    self.tools_used += 1
                    self.current_agent = "tools"
                    time.sleep(0.2)  # Pause visuelle
                    continue
                    
                if isinstance(msg, (AIMessageChunk, AIMessage)):
                    content = msg.content or ""
                    if content:
                        response_content += content
                        self.current_message = response_content
                        time.sleep(0.03)  # Effet de frappe
                        
        except Exception as e:
            self.current_message = f"❌ Erreur: {str(e)}"
            
        finally:
            # Sauvegarder la réponse
            if self.current_message:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": self.current_message,
                    "agent": self.current_agent,
                    "timestamp": datetime.now()
                })
                
            self.is_processing = False
            self.current_message = ""
            self.current_agent = "chatbot"
            
    def run_interface(self):
        """Lance l'interface principale"""
        self.console.clear()
        self.console.print("🎉 Interface Rich Agent IA", style="bold green")
        self.console.print("Utilisez les commandes ci-dessous:\n", style="dim")
        
        with Live(self.create_main_layout(), console=self.console, refresh_per_second=8) as live:
            
            while True:
                try:
                    # Mettre à jour l'affichage
                    live.update(self.create_main_layout())
                    
                    if not self.is_processing:
                        # Arrêter Live pour permettre l'input
                        live.stop()
                        
                        # Afficher le prompt
                        config = self.get_agent_config(self.current_agent)
                        self.console.print(f"\n[{config['color']}]💭 Votre message:[/{config['color']}] ", end="")
                        
                        try:
                            user_input = input().strip()
                        except (EOFError, KeyboardInterrupt):
                            self.console.print("\n👋 Au revoir!", style="bold yellow")
                            break
                            
                        # Redémarrer Live
                        live.start()
                        
                        if user_input.lower() in {"quit", "exit", "q", "bye", "stop"}:
                            self.console.print("👋 Merci d'avoir utilisé l'Agent IA!", style="bold yellow")
                            break
                            
                        if user_input:
                            # Traiter dans un thread séparé pour éviter le blocage
                            thread = threading.Thread(
                                target=self.process_agent_message,
                                args=(user_input,),
                                daemon=True
                            )
                            thread.start()
                    else:
                        time.sleep(0.1)
                        
                except KeyboardInterrupt:
                    self.console.print("\n🛑 Interface interrompue.", style="bold red")
                    break
                    
    def run(self):
        """Point d'entrée principal"""
        self.console.print("🚀 Initialisation de l'Agent IA...", style="bold blue")
        
        if not self.init_agent():
            self.console.print("❌ Impossible d'initialiser l'agent", style="bold red")
            return
            
        self.console.print("✅ Agent IA prêt!", style="bold green")
        time.sleep(1)
        
        try:
            self.run_interface()
        except Exception as e:
            self.console.print(f"❌ Erreur fatale: {e}", style="bold red")


def main():
    """Point d'entrée principal"""
    interface = ModernAgentInterface()
    interface.run()


if __name__ == "__main__":
    main()
