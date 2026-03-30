<div align="center">

```
  ██████╗ ██╗  ██╗ ██████╗ ███╗  ██╗
 ██╔══██╗╚██╗██╔╝██╔═══██╗████╗ ██║
 ███████║ ╚███╔╝ ██║   ██║██╔██╗██║
 ██╔══██║ ██╔██╗ ██║   ██║██║╚████║
 ██║  ██║██╔╝ ██╗╚██████╔╝██║ ╚███║
 ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚══╝
```

**Agent IA personnel en terminal — LangGraph · multi-backend · HITL**

![Python](https://img.shields.io/badge/Python-3.11+-orange?style=flat-square&logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-blue?style=flat-square)
![Ollama](https://img.shields.io/badge/Ollama-local%20%2B%20cloud-black?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

</div>

---

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/kaiiine/ai-agent/main/install.sh | sh
```

> Clone le repo, installe les dépendances, configure les APIs, télécharge les modèles Ollama, crée un alias `axon` global.

```bash
# Ou manuellement :
git clone https://github.com/kaiiine/ai-agent.git && cd ai-agent && bash setup.sh
```

**Prérequis :** Python 3.11+ · [Ollama](https://ollama.com/download)

---

## Démarrage rapide

```bash
axon
# ou
cd ai-agent && source venv/bin/activate && python -m src.ui.main
```

```
┌─────────────────────────────────────────────────────────┐
│  Axon  ·  ollama_cloud  ·  qwen3-coder:cloud            │
│                                                          │
│  > Résume mes derniers emails non lus                    │
│  > Va dans mon projet X et corrige le bug dans auth.ts   │
│  > Cherche des papers sur les RAG hybrides               │
│  > Quel temps fait-il à Paris ?                          │
└─────────────────────────────────────────────────────────┘
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    UI Terminal (Rich)                    │
│   streaming · commands · panels · picker · review       │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  Orchestrateur (LangGraph)               │
│                                                          │
│   ┌───────────────────┐    ┌──────────────────────────┐  │
│   │   ToolRetriever   │    │     chatbot node (LLM)   │  │
│   │  nomic-embed-text │───▶│  bind_tools(relevant)    │  │
│   │  + multi-anchors  │    └────────────┬─────────────┘  │
│   └───────────────────┘                │                 │
│                              ┌─────────▼─────────────┐  │
│                              │       ToolNode         │  │
│                              │  (exécute tool calls)  │  │
│                              └────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────────┐
          │              │                  │
   ┌──────▼──┐   ┌───────▼──────┐   ┌──────▼──────────────┐
   │ Agents  │   │  Shell / Git │   │  Coding Specialist   │
   │ Google  │   │  Filesystem  │   │  LLM dédié + HITL   │
   │ Slack   │   │  System      │   │  propose_file_change │
   │ Jira    │   └──────────────┘   └─────────────────────┘
   │ Arxiv…  │
   └─────────┘
```

**Flux d'une requête :**

1. L'utilisateur tape un message
2. Le `ToolRetriever` sélectionne les outils sémantiquement pertinents (parmi ~40)
3. L'orchestrateur (LLM) appelle les outils nécessaires
4. Les réponses sont streamées token par token
5. Pour les tâches de code → `run_coding_agent` délègue au spécialiste avec workflow HITL

---

## Agents & outils

### Recherche & information
| Outil | Description |
|-------|-------------|
| `web_research_report` | Recherche web approfondie via Tavily |
| `arxiv_search` · `arxiv_get_paper` | Papers académiques |
| `get_weather_by_city` | Météo en temps réel |
| `get_current_time` | Date et heure |

### Fichiers locaux
| Outil | Description |
|-------|-------------|
| `local_find_file` | Trouver un fichier par nom/pattern |
| `local_list_directory` | Lister un répertoire |
| `local_read_file` | Lire le contenu d'un fichier |

### Shell & système
| Outil | Description |
|-------|-------------|
| `shell_run` | Exécuter une commande (avec garde destructive) |
| `shell_cd` · `shell_pwd` · `shell_ls` | Navigation (fuzzy) |
| `notify` | Notification desktop |
| `clipboard_read` · `clipboard_write` | Presse-papiers |
| `screenshot_take` | Capture d'écran |
| `process_list` · `process_kill` · `wifi_info` | Système |

### Git
| Outil | Description |
|-------|-------------|
| `git_status` · `git_log` · `git_diff` | Inspection |
| `git_suggest_commit` | Suggestion de message de commit |
| `url_fetch` | Fetch d'une URL distante |

### Google Workspace
| Outil | Description |
|-------|-------------|
| `gmail_search` · `gmail_summarize` | Lire les emails |
| `gmail_send_email` · `gmail_edit_draft` · `gmail_confirm_send` | Envoyer |
| `calendar_list_events` · `calendar_create_event` · … | Agenda |
| `drive_list_files` · `drive_read_file` · `drive_find_file_id` · … | Drive |
| `google_docs_create` · `google_docs_update` · `google_docs_read` | Docs |
| `create_presentation` · `add_slide` | Slides |

### Slack
`slack_find_user` · `slack_list_channels` · `slack_read_channel` · `slack_get_mentions` · `slack_list_dms` · `slack_send_message` · `slack_search_messages`

### Jira
| Outil | Description |
|-------|-------------|
| `jira_get_my_issues` | Tickets assignés à l'utilisateur |
| `jira_get_issue` | Détails d'un ticket par clé (ex: KAN-42) |
| `jira_search_issues` | Recherche JQL libre |
| `jira_get_project_summary` | Avancement global : tickets par statut, story points |
| `jira_get_sprint_issues` | Tickets du sprint actif (fallback Kanban) |
| `jira_list_projects` | Projets accessibles |
| `jira_create_issue` | Créer un ticket (Task, Story, Bug, Epic) |
| `jira_create_issues_bulk` | Créer plusieurs tickets en masse avec hiérarchie Epic→Story→Task |
| `jira_assign_issue` | Assigner à soi ou à quelqu'un |
| `jira_update_issue` | Modifier titre, description, priorité |
| `jira_transition_issue` | Changer le statut (To Do → In Progress → Done) |
| `jira_add_comment` | Commenter un ticket |
| `jira_get_issue_comments` | Lire les commentaires |
| `jira_get_workload` | Répartition des tickets par membre |
| `jira_search_users` | Trouver un utilisateur par nom |
| `jira_move_issue` | Déplacer un ticket vers un autre projet |

### Agent de code (HITL)
| Outil | Description |
|-------|-------------|
| `run_coding_agent` | Délègue au spécialiste de code |
| `dev_plan_create` | Crée un plan d'exécution |
| `dev_plan_step_done` | Valide une étape |
| `dev_explain` | Présente l'analyse à l'utilisateur |
| `propose_file_change` | Propose une modification (diff + approbation) |
| `find_git_repos` | Trouve les repos git locaux |

---

## Agent de code — workflow HITL

Chaque tâche de code suit un workflow strict avec approbation humaine à chaque modification :

```
1. dev_plan_create(steps=[...])        ← Toujours en premier
       ↓
2. find_git_repos + shell_cd           ← Navigation vers le bon projet
       ↓
3. local_read_file / shell_run         ← Analyse du code existant
       ↓
4. dev_explain(message=...)            ← Explication à l'utilisateur
       ↓
5. propose_file_change(path, content)  ← Diff affiché + demande d'approbation
   ┌──────────────────────────────┐
   │  ✓ Appliquer                 │
   │  ✗ Refuser                   │
   │  ~ Préciser                  │
   └──────────────────────────────┘
       ↓
6. Vérification auto (build/lint)      ← npm run build · pytest · tsc…
       ↓
7. Résumé final
```

Les fichiers ne sont **jamais écrits directement** — `shell_run` bloque toute écriture via `sed -i`, `cat >`, etc.

---

## ToolRetriever — sélection sémantique

À chaque requête, seuls les outils pertinents sont injectés dans le contexte :

```
Requête → OllamaEmbeddings (nomic-embed-text) → Chroma vectorstore → top-k outils
                                                        ↓
                                              Expansion par groupes
                                              (git détecté → tous les outils git)
```

**Multi-vector anchors** : les méta-outils abstraits (comme `run_coding_agent`) sont indexés avec plusieurs formulations sémantiques couvrant différentes intentions utilisateur. Résultat : une requête comme *"va dans mon repo et refais l'UI"* sélectionne toujours `run_coding_agent` même si les mots-clés ne matchent pas directement sa description.

---

## Backends LLM

Configurables à la volée via `/backend` :

| Backend | Modèle par défaut | Usage |
|---------|-------------------|-------|
| `ollama` | `qwen2.5:7b` | 100% local (GPU) |
| `ollama_cloud` | `kimi-k2:cloud` | Cloud via Ollama |
| `groq` | `llama-3.3-70b-versatile` | API Groq |

Le spécialiste de code utilise `qwen3-coder-next:cloud` (cloud) ou le modèle de l'orchestrateur (local).

---

## Commandes

| Commande | Description |
|----------|-------------|
| `/attach` | Joindre un fichier (code, texte, PDF, image) |
| `/paste` | Coller depuis le presse-papiers |
| `/attachments` | Lister les pièces jointes |
| `/detach [fichier]` | Supprimer une pièce jointe |
| `/letter` | Générer une lettre de motivation |
| `/upgrade` | Améliorer une lettre existante |
| `/backend <b>` | Changer de backend : `groq` · `ollama` · `ollama_cloud` |
| `/model <nom>` | Changer de modèle (picker interactif si sans argument) |
| `/temp <val>` | Changer la température |
| `/mode <ask\|auto>` | Mode édition fichiers (demande / automatique) |
| `/lang <fr\|en>` | Forcer la langue |
| `/new` | Nouveau thread |
| `/save` | Sauvegarder le transcript |
| `/config` | Configuration courante |
| `/debug` | Mode debug |
| `/dump` | Afficher tous les messages du thread |
| `q` · `exit` | Quitter |

**Raccourcis :** `Ctrl+O` → `/attach` · `Ctrl+P` → `/paste`

---

## Configuration

### Variables d'environnement (`.env`)

```env
# LLM
GROQ_API_KEY=gsk_...
OLLAMA_API_KEY=ollama_...          # Optionnel (Ollama Cloud)
OLLAMA_HOST=http://127.0.0.1:11434

# Recherche web
TAVILY_API_KEY=tvly-...

# Slack
SLACK_USER_TOKEN=xoxp-...          # User Token (OAuth & Permissions → User Token Scopes)

# Jira
JIRA_URL=https://ton-domaine.atlassian.net
JIRA_EMAIL=ton@email.com
JIRA_API_KEY=ATATT3x...            # https://id.atlassian.com/manage-profile/security/api-tokens

# Divers
PROJECTS_DIR=/home/user/projets    # Racine des projets (accélère find_git_repos)
APP_ENV=dev
```

Google (Gmail · Calendar · Drive · Docs · Slides) utilise OAuth2 via `gcp-oauth.keys.json` — voir `bash setup.sh --config-only`.

### `configs/base.yaml`

```yaml
llm_backend: "ollama_cloud"        # ollama | ollama_cloud | groq

ollama:
  model: "qwen2.5:7b"
  temperature: 0.0

groq:
  model: "llama-3.3-70b-versatile"

search:
  backend: "tavily"
  max_results: 10
```

### Modèles Ollama

```bash
ollama pull nomic-embed-text    # Obligatoire (ToolRetriever)
ollama pull qwen2.5:7b          # Backend local (optionnel)
```

---

## Structure du projet

```
ai-agent/
├── install.sh                     # Installateur one-line (curl)
├── setup.sh                       # Déploiement interactif
├── Makefile                       # make agent | install | lint | clean
├── requirements.txt
├── .env.sample                    # Template des variables d'environnement
├── configs/
│   └── base.yaml                  # Config LLM, search, backends
│
└── src/
    ├── ui/
    │   ├── app.py                 # Entrypoint CLI
    │   ├── streaming.py           # Stream LLM + commandes
    │   ├── commands.py            # Handler /slash
    │   ├── panels.py              # Composants Rich
    │   ├── attachments.py         # Fichiers, images, PDF
    │   ├── review.py              # UI review des diffs
    │   ├── picker.py              # Sélecteur interactif
    │   ├── edit_mode.py           # Mode ask / auto
    │   └── transcript.py          # Sauvegarde conversations
    │
    ├── orchestrator/
    │   ├── graph.py               # LangGraph (chatbot + ToolNode)
    │   ├── registry.py            # Enregistrement de tous les outils
    │   ├── state.py               # GlobalState TypedDict
    │   └── tool_retriever.py      # Sélection sémantique (Chroma + anchors)
    │
    ├── llm/
    │   ├── models.py              # Factories LLM
    │   └── prompts.py             # System prompt Axon
    │
    ├── infra/
    │   ├── settings.py            # Configuration Pydantic
    │   ├── checkpoint.py          # Checkpointer LangGraph
    │   └── google_auth.py         # OAuth Google
    │
    └── agents/
        ├── coding/
        │   ├── specialist.py      # Loop LLM spécialiste (150 itérations max)
        │   ├── tools.py           # dev_plan · propose_file_change · dev_explain
        │   └── pending.py         # File de changements en attente
        ├── gmail/ · google_calendar/ · google_drive/
        ├── google_doc/ · google_slide/
        ├── jira/                  # Tickets, Epics, sprints, workload
        ├── slack/ · shell/ · git/ · filesystem/
        ├── system/ · arxiv/ · time/ · weather/ · search/
        └── image/
```

---

## Makefile

```bash
make agent      # Lancer Axon
make install    # Installer les dépendances
make lint       # Vérifier le code
make clean      # Nettoyer le cache
```

---

<div align="center">

Made with ♥ by [@kaiiine](https://github.com/kaiiine)

</div>
