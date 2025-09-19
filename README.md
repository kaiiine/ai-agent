# AI Agent - Interface Rich Moderne

Un agent IA conversationnel avec une interface Rich moderne et interactive.

## 🚀 Fonctionnalités

- **Interface Rich moderne** : Interface terminal avec couleurs et mise en page dynamique
- **Agents spécialisés** : Détection automatique et changement de couleur selon l'agent utilisé
  - 🔍 **Search Agent** (Cyan) : Recherche web via Tavily
  - 🌤️ **Weather Agent** (Bleu) : Informations météo
  - 💬 **Chat Agent** (Vert) : Conversation générale
  - 🔧 **Tool Agent** (Jaune) : Exécution d'outils
- **Streaming en temps réel** : Réponses affichées token par token
- **Historique de conversation** : Sauvegarde des échanges
- **Statistiques de session** : Temps, messages, outils utilisés

## 📦 Installation

1. Cloner le repository
2. Installer les dépendances :
```bash
pip install -r requirements.txt
```

3. Configurer les variables d'environnement (copier `.env.sample` vers `.env`) :
```bash
cp .env.sample .env
# Éditer .env avec vos clés API
```

## 🎮 Utilisation

### Interface Rich Moderne (Recommandée)
```bash
python run_modern_interface.py
```

### Interface Rich Standard  
```bash
python run_rich_interface.py
```

### Interface CLI Simple
```bash
python src/app.py
```

### Test de l'interface
```bash
python test_rich.py
```

## 🎨 Aperçu de l'Interface

L'interface Rich affiche :
- **En-tête** : Status de l'agent actuel avec indicateurs visuels
- **Barre d'agents** : Agents disponibles avec changement de couleur selon l'agent actif
- **Conversation** : Historique des messages avec icônes et couleurs par agent
- **Zone de saisie** : Prompt adaptatif selon l'agent

### Couleurs par Agent
- 🔍 **Search** : Cyan - Questions de recherche web
- 🌤️ **Weather** : Bleu - Questions météo 
- 💬 **Chat** : Vert - Conversation générale
- 🔧 **Tools** : Jaune - Pendant l'exécution d'outils

## 🛠️ Configuration

Le projet utilise :
- **LangGraph** pour l'orchestration des agents
- **Ollama** comme LLM (modèle : qwen2.5:7b)
- **Rich** pour l'interface terminal
- **Tavily** pour la recherche web
- **Open-Meteo** pour la météo

Configuration dans `configs/base.yaml` et variables d'environnement.

## 🔧 Développement

Structure du projet :
```
src/
├── agents/           # Agents spécialisés
├── llm/             # Modèles de langage  
├── orchestrator/    # Orchestration et routage
├── infra/           # Infrastructure et settings
└── utils/           # Utilitaires

interfaces/
├── rich_interface.py         # Interface Rich standard
├── modern_rich_interface.py  # Interface Rich moderne
└── app.py                   # Interface CLI simple
```

## 🤝 Commandes

- Tapez votre question pour interagir avec l'agent
- L'agent est automatiquement sélectionné selon votre question
- Tapez `quit`, `exit`, `q` ou `bye` pour quitter
- `Ctrl+C` pour interruption forcée

## 📝 Exemples d'utilisation

- "Quel temps fait-il à Paris ?" → Agent Weather (Bleu)
- "Recherche des infos sur Python" → Agent Search (Cyan)  
- "Bonjour comment ça va ?" → Agent Chat (Vert)

L'interface change automatiquement de couleur selon l'agent détecté !