# Axon — Agent IA personnel en terminal

Interface conversationnelle en ligne de commande propulsée par LangGraph, avec agents spécialisés, sélection sémantique des outils, et support multi-backend LLM.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    UI Terminal (Rich)                    │
│   streaming.py · commands.py · panels.py · picker.py    │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  Orchestrateur (LangGraph)                │
│                                                          │
│   ┌──────────────┐     ┌─────────────────────────────┐  │
│   │  ToolRetriever│     │      chatbot node (LLM)     │  │
│   │  (Chroma +    │────▶│  bind_tools(selected_tools) │  │
│   │  embeddings)  │     └──────────┬──────────────────┘  │
│   └──────────────┘                │                      │
│                         ┌─────────▼──────────────────┐  │
│                         │       ToolNode              │  │
│                         │  (exécute les tool calls)   │  │
│                         └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         │
           ┌─────────────┼────────────────┐
           │             │                │
    ┌──────▼──┐   ┌─────▼──────┐  ┌──────▼──────────┐
    │  Agents │   │   Shell /  │  │ Coding Specialist│
    │ Google  │   │  Git / FS  │  │  (LLM dédié +   │
    │ Slack   │   │  System    │  │  propose_file)   │
    │ Gmail…  │   └────────────┘  └─────────────────┘
    └─────────┘
```

**Flux d'une requête :**

1. L'utilisateur tape un message
2. Le `ToolRetriever` sélectionne les outils sémantiquement pertinents (parmi ~40)
3. L'orchestrateur (LLM) appelle les outils nécessaires
4. Les réponses sont streamées token par token dans le terminal
5. Pour les tâches de code, le spécialiste `run_coding_agent` prend le relai avec son propre loop

---

## Agents et outils disponibles

### Recherche et information
| Outil | Description |
|-------|-------------|
| `web_research_report` | Recherche web via Tavily |
| `arxiv_search` / `arxiv_get_paper` | Recherche de papers académiques |
| `get_weather_by_city` | Météo en temps réel |
| `get_current_time` | Date et heure courante |

### Système de fichiers local
| Outil | Description |
|-------|-------------|
| `local_find_file` | Trouver un fichier par pattern |
| `local_list_directory` | Lister un répertoire |
| `local_read_file` | Lire le contenu d'un fichier |

### Shell et système
| Outil | Description |
|-------|-------------|
| `shell_run` | Exécuter une commande shell |
| `shell_cd` / `shell_pwd` / `shell_ls` | Navigation |
| `notify` | Notification système |
| `clipboard_read` / `clipboard_write` | Presse-papiers |
| `screenshot_take` | Capture d'écran |
| `process_list` / `process_kill` | Gestion des processus |
| `wifi_info` | Infos réseau |

### Git
| Outil | Description |
|-------|-------------|
| `git_status` / `git_log` / `git_diff` | Inspection du repo |
| `git_suggest_commit` | Suggestion de message de commit |
| `url_fetch` | Fetch d'une URL |

### Gmail
| Outil | Description |
|-------|-------------|
| `gmail_search` | Chercher des emails |
| `gmail_summarize` | Résumer un email |
| `gmail_send_email` / `gmail_edit_draft` / `gmail_confirm_send` | Envoi d'emails |

### Google Calendar
`calendar_list_events` · `calendar_create_event` · `calendar_update_event` · `calendar_delete_event` · `calendar_list_calendars` · `calendar_search_events`

### Google Drive / Docs / Slides
`drive_list_files` · `drive_read_file` · `drive_find_file_id` · `drive_delete_file` · `drive_get_file_metadata`
`google_docs_create` · `google_docs_update` · `google_docs_read`
`create_presentation` · `add_slide`

### Slack
`slack_find_user` · `slack_list_channels` · `slack_read_channel` · `slack_get_mentions` · `slack_list_dms` · `slack_send_message` · `slack_search_messages`

### Agent de code (spécialiste)
| Outil | Description |
|-------|-------------|
| `run_coding_agent` | Délègue une tâche de code au spécialiste |
| `dev_plan_create` | Crée un plan d'exécution (étapes) |
| `dev_plan_step_done` | Valide une étape du plan |
| `dev_explain` | Présente l'analyse à l'utilisateur |
| `propose_file_change` | Propose une modification de fichier (avec diff + approbation) |
| `find_git_repos` | Trouve les repos git locaux |

---

## Backends LLM

Trois backends configurables à la volée via `/backend` :

| Backend | Modèle par défaut | Usage |
|---------|-------------------|-------|
| `ollama` | `qwen2.5:7b` | Local (GPU requis) |
| `ollama_cloud` | `gpt-oss:120b-cloud` | Cloud via Ollama |
| `groq` | `llama-3.3-70b-versatile` | API Groq |

Le spécialiste de code utilise `qwen3-coder-next:cloud` (cloud) ou le même modèle que l'orchestrateur (local).

---

## Sélection sémantique des outils (ToolRetriever)

À chaque requête, le `ToolRetriever` sélectionne les outils les plus pertinents :

```
Requête → OllamaEmbeddings (nomic-embed-text) → Chroma vectorstore → top-k outils
```

- Seuls les outils sélectionnés sont injectés dans le system prompt → moins de tokens, meilleure précision
- Le modèle d'embedding tourne localement via Ollama

---

## Agent de code — workflow

Quand une tâche de code est détectée, `run_coding_agent` lance un loop dédié :

```
1. dev_plan_create(steps=[...])        ← TOUJOURS en premier
2. find_git_repos / local_read_file    ← Analyse du projet
3. dev_explain(message=...)            ← Explication à l'utilisateur
4. propose_file_change(path, content)  ← Proposition avec diff
5. dev_plan_step_done(N)               ← Validation de l'étape
6. Résumé final
```

Les fichiers ne sont **jamais écrits directement** — chaque modification passe par `propose_file_change` qui affiche un diff et demande approbation (`/mode ask`) ou applique automatiquement (`/mode auto`).

---

## Interface — commandes

| Commande | Description |
|----------|-------------|
| `/attach` | Joindre un fichier (code, texte, PDF, image) |
| `/paste` | Coller une image depuis le presse-papiers |
| `/attachments` | Lister les pièces jointes en attente |
| `/detach [fichier]` | Supprimer une ou toutes les pièces jointes |
| `/letter` | Générer une lettre de motivation (attach CV + colle l'offre) |
| `/upgrade` | Améliorer une lettre existante |
| `/backend <b>` | Changer de backend : `groq` · `ollama` · `ollama_cloud` |
| `/model <nom>` | Changer de modèle (picker interactif si sans argument) |
| `/temp <val>` | Changer la température (ex: `0.7`) |
| `/mode <ask\|auto>` | Mode édition fichiers |
| `/lang <fr\|en>` | Forcer la langue de réponse |
| `/new` | Nouveau thread de conversation |
| `/save` | Sauvegarder le transcript |
| `/config` | Afficher la configuration courante |
| `/debug` | Activer/désactiver le mode debug |
| `/dump` | Afficher tous les messages du thread |
| `q / exit` | Quitter |

**Raccourcis clavier :**
- `Ctrl+O` → `/attach`
- `Ctrl+P` → `/paste`

---

## Structure du projet

```
ai-agent/
├── configs/
│   └── base.yaml                  # Config principale (LLM, search, backends)
├── .env                           # Clés API (non versionné)
├── .env.sample                    # Template des variables d'environnement
├── Makefile                       # Commandes build/run
├── requirements.txt               # Dépendances Python
│
└── src/
    ├── ui/
    │   ├── app.py                 # Entrypoint CLI
    │   ├── main.py                # Wrapper __main__
    │   ├── streaming.py           # Stream LLM + gestion des commandes
    │   ├── commands.py            # Handler des commandes /slash
    │   ├── panels.py              # Composants Rich (bannière, panels)
    │   ├── attachments.py         # Pièces jointes (fichiers, images, PDF)
    │   ├── review.py              # UI de review des diffs
    │   ├── picker.py              # Sélecteur interactif (flèches)
    │   ├── edit_mode.py           # Mode ask / auto
    │   ├── render.py              # Rendu Markdown
    │   ├── config.py              # SessionConfig
    │   ├── language.py            # Détection de langue
    │   └── transcript.py          # Sauvegarde des conversations
    │
    ├── orchestrator/
    │   ├── graph.py               # LangGraph (chatbot node + ToolNode)
    │   ├── registry.py            # Enregistrement de tous les outils
    │   ├── state.py               # GlobalState TypedDict
    │   └── tool_retriever.py      # Sélection sémantique (Chroma)
    │
    ├── llm/
    │   ├── models.py              # Factories LLM (Ollama, Groq, Cloud)
    │   └── prompts.py             # System prompt Axon
    │
    ├── infra/
    │   ├── settings.py            # Configuration Pydantic (YAML + .env)
    │   ├── checkpoint.py          # Checkpointer LangGraph
    │   └── google_auth.py         # OAuth Google
    │
    └── agents/
        ├── search/tools.py
        ├── weather/tools.py
        ├── gmail/tools.py
        ├── google_calendar/tools.py
        ├── google_doc/tools.py
        ├── google_drive/tools.py
        ├── google_slide/tools.py
        ├── slack/tools.py
        ├── shell/tools.py
        ├── git/tools.py
        ├── filesystem/
        │   ├── tools.py
        │   └── letter.py          # Génération DOCX/PDF lettre de motivation
        ├── system/tools.py
        ├── arxiv/tools.py
        ├── time/tools.py
        └── coding/
            ├── specialist.py      # Loop LLM spécialiste (150 itérations max)
            ├── tools.py           # dev_plan, propose_file_change, dev_explain
            └── pending.py         # File de changements en attente
```

---

## Installation

```bash
# Prérequis : Python 3.11+, Ollama installé et en cours d'exécution

git clone <repo>
cd ai-agent

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.sample .env
# Remplir les clés API dans .env

# Lancer
python -m src.ui.main
```

### Variables d'environnement (.env)

```env
GOOGLE_API_KEY=...        # Google Cloud (Calendar, Drive, Docs, Gmail, Slides)
TAVILY_API_KEY=...        # Recherche web
GROQ_API_KEY=...          # API Groq (si backend groq)
OLLAMA_API_KEY=...        # Ollama Cloud (si backend ollama_cloud avec compte)
OLLAMA_HOST=http://127.0.0.1:11434
APP_ENV=dev
```

### Modèles Ollama requis

```bash
ollama pull nomic-embed-text     # Obligatoire (ToolRetriever)
ollama pull qwen2.5:7b           # Si backend ollama local
```

### Makefile

```bash
make agent      # Lancer l'interface Rich
make install    # Installer les dépendances
make test       # Lancer les tests
make lint       # Vérifier le code
make clean      # Nettoyer le cache
```

---

## Configuration (configs/base.yaml)

```yaml
llm_backend: "ollama_cloud"    # ollama | ollama_cloud | groq

ollama:
  model: "qwen2.5:7b"
  temperature: 0.0

groq:
  model: "llama-3.3-70b-versatile"

search:
  backend: "tavily"
  max_results: 10
```

Tous les paramètres sont modifiables à chaud via les commandes `/backend`, `/model`, `/temp`.
