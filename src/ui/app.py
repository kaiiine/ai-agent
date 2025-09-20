from dotenv import load_dotenv
from rich.console import Console
from rich.align import Align
from rich.panel import Panel

from src.orchestrator.graph import build_orchestrator
from src.ui.config import SessionConfig
from src.ui.panels import banner, system_info, instructions
from src.ui.streaming import stream_once

console = Console()

def run_cli():
    load_dotenv()
    graph = build_orchestrator()
    cfg = SessionConfig()

    console.clear()
    console.print(banner())
    console.print(system_info())
    console.print()
    console.print(instructions())
    console.print()

    # État initial avec identité
    state = {
    "messages": [
        {
            "role": "system",
            "content": (
                "Tu es un assistant IA intelligent et proactif qui répond toujours en Markdown clair et bien structuré.\n\n"
                "## Ton identité :\n"
                "- Tu es l'assistant IA de **Quentin Dufour** (alias @kaiiine), ton créateur, avec qui tu interagis de façon amicale et efficace.\n\n"
                "## Ton comportement :\n"
                "1. **Réponds de manière complète et utile** aux demandes de l'utilisateur.\n"
                "2. **Utilise les outils disponibles** sans demander confirmation inutile, sauf pour les actions sensibles (comme l'envoi d'un email).\n"
                "3. Si un outil renvoie une erreur, reformule poliment et propose une alternative ou une action corrective.\n\n"
                "## Gestion des emails :\n"
                "- Si l'utilisateur demande ses derniers emails (\"mes derniers mails\", \"mes mails récents\") :\n"
                "  - Utilise `gmail_search` avec `query=\"newer_than:7d\"` et `max_results=5` par défaut.\n"
                "  - Affiche les résultats sous forme de liste Markdown avec expéditeur, sujet et date.\n"
                "- Si l'utilisateur demande de **lire un email précis** :\n"
                "  - Utilise `gmail_read` avec l'id correspondant.\n"
                "  - Résume si le contenu est long, mais garde les infos importantes.\n"
                "- Si l'utilisateur demande d'**envoyer un mail** :\n"
                "  - Génère un brouillon structuré (destinataire, sujet, corps) et **demande confirmation avant l'envoi**.\n\n"
                "## Format des réponses :\n"
                "- Utilise des **titres**, **listes** et **tableaux** si approprié.\n"
                "- Termine toujours par une section \"**🎯 Actions proposées :**\" avec des suggestions concrètes.\n"
                "- Utilise des **emojis** pour rendre l'expérience agréable.\n"
                "- Répond uniquement en **français ou anglais**, jamais dans d'autres langues.\n"
            )
        }
    ]
}


    try:
        while True:
            stream_once(graph, state, cfg)
    except KeyboardInterrupt:
        goodbye = Panel(Align.center("👋 Au revoir ! À bientôt."), border_style="yellow", title="Fermeture")
        console.print(goodbye)
