<div align="center">

```
  ██████╗ ██╗  ██╗ ██████╗ ███╗  ██╗
 ██╔══██╗╚██╗██╔╝██╔═══██╗████╗ ██║
 ███████║ ╚███╔╝ ██║   ██║██╔██╗██║
 ██╔══██║ ██╔██╗ ██║   ██║██║╚████║
 ██║  ██║██╔╝ ██╗╚██████╔╝██║ ╚███║
 ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚══╝
```

**Agent IA personnel en terminal — LangGraph · multi-backend · HITL · context-aware**

![Python](https://img.shields.io/badge/Python-3.11+-orange?style=flat-square&logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-blue?style=flat-square)
![Ollama](https://img.shields.io/badge/Ollama-local%20%2B%20cloud-black?style=flat-square)
![Gemini](https://img.shields.io/badge/Gemini-2.0%20Flash-4285F4?style=flat-square&logo=google)
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

# Reconfigurer les intégrations sans réinstaller :
bash setup.sh --config-only
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
·············································· ○ 0% ···············································
› Résume mes derniers emails non lus
› Va dans mon projet X et corrige le bug dans auth.ts
› Cherche des papers sur les RAG hybrides sur arxiv
› Quel temps fait-il à Paris demain ?
› regarde @src/agents/jira/tools.py et optimise _fmt_issue
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         UI Terminal (Rich + prompt_toolkit)          │
│  streaming · commands · completer (@mention) · plan_mode · review   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                     Orchestrateur (LangGraph)                        │
│                                                                      │
│   ┌─────────────────┐    ┌──────────────────────────────────────┐   │
│   │  ToolRetriever  │    │         chatbot node (LLM)           │   │
│   │ nomic-embed-text│───▶│  bind_tools(relevant, plan_filtered) │   │
│   │  + anchors k=7  │    └─────────────────┬────────────────────┘   │
│   └─────────────────┘                      │                        │
│                               ┌────────────▼──────────────────┐    │
│                               │       CachedToolNode          │    │
│                               │  cache → execute → redact     │    │
│                               └───────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────────┐
          │                  │                      │
   ┌──────▼──┐     ┌─────────▼───────┐    ┌────────▼───────────────┐
   │ Agents  │     │  Shell / Git    │    │  Coding Specialist     │
   │ Google  │     │  Filesystem     │    │  LLM dédié + HITL      │
   │ Slack   │     │  System         │    │  propose_file_change   │
   │ Jira    │     └─────────────────┘    │  SnapshotStore (/undo) │
   │ Arxiv…  │                            └────────────────────────┘
   └─────────┘
```

**Flux d'une requête :**

1. L'utilisateur tape un message (avec éventuel `@mention` de fichier)
2. Les mentions `@fichier` sont résolues et injectées dans le message
3. Le `ToolRetriever` sélectionne les k=7 outils les plus pertinents
4. En **mode plan** : les outils d'écriture sont retirés de la liste
5. L'orchestrateur (LLM) appelle les outils, les résultats passent par le cache et le redacteur
6. Les réponses sont streamées token par token
7. Pour les tâches de code → `run_coding_agent` délègue au spécialiste HITL

---

## Backends LLM

Configurables à la volée via `/backend` ou dans `configs/base.yaml` :

| Backend | Modèle par défaut | Tokens contexte | Usage |
|---------|-------------------|----------------|-------|
| `gemini` | `gemini-2.0-flash` | **1 000 000** | Gratuit, recommandé |
| `ollama_cloud` | `kimi-k2:1t-cloud` | 128 000 | Cloud Ollama |
| `groq` | `llama-3.3-70b-versatile` | 131 072 | API Groq, rapide |
| `ollama` | `qwen2.5:7b` | 131 072 | 100% local (GPU) |

> **Gemini 2.0 Flash** — gratuit, 15 req/min, 1 500 req/jour, 1M tokens de contexte. La compression de contexte ne se déclenche presque jamais.

Le spécialiste de code s'adapte au backend actif : Gemini, Groq, ou le modèle Ollama local.

---

## Optimisations contexte & tokens

### Prompt système adaptatif

Le prompt système est construit dynamiquement à chaque requête : seules les sections pertinentes aux outils sélectionnés sont incluses. Réduction typique : **40–60 %** de tokens vs un prompt monolithique.

```
Requête "cherche sur arxiv" → sections incluses : CORE + RECHERCHE
Requête "modifie mon code"  → sections incluses : CORE + FICHIERS + SHELL + DÉVELOPPEMENT
```

### Compression de contexte proactive

Avant chaque appel LLM, si la fenêtre de contexte est chargée à plus de 85 % :

1. Les messages récents (≥ `_PRUNE_PROTECT` tokens) sont protégés
2. Les échanges plus anciens sont résumés par le LLM
3. Si la résumé échoue : **pruning intelligent** — supprime le round outil complet le plus ancien (AIMessage + ses ToolMessages) avant de toucher aux messages conversationnels

### Cache de résultats outils (session)

Les outils de lecture sont mis en cache pour la durée de la session avec des TTLs par outil :

| Outil | TTL |
|-------|-----|
| `local_read_file` | 30 s |
| `git_status` | 15 s |
| `git_diff` | 20 s |
| `web_research_report` | 300 s |
| `web_search_news` | 120 s |

Les outils d'écriture (`git_add`, `git_commit`, `git_stash`) invalident automatiquement les caches dépendants.

### Redaction des données sensibles

Sur les backends cloud (`gemini`, `groq`, `ollama_cloud`), les résultats des outils sont filtrés avant d'entrer dans le contexte LLM :

- Clés API (`API_KEY=`, `SECRET=`, `TOKEN=`, préfixes `sk-`, `gsk_`, `AIzaSy`…)
- Tokens Bearer / Authorization headers
- Clés privées PEM
- Fichiers sensibles complets (`.env`, `credentials.json`, `id_rsa`…) → remplacés par un message explicite

---

## Mode Plan (`Ctrl+T`)

Bascule entre **BUILD** (mode normal) et **PLAN** (lecture seule).

```
·············· ◆ PLAN ················
 PLAN   Analyse mon projet et propose une refonte de l'architecture auth
```

En mode PLAN :
- Le prompt affiche ` PLAN ` en orange à la place de `›`
- Le séparateur affiche `◆ PLAN`
- Tous les outils d'écriture sont retirés (shell_run, git_commit, run_coding_agent, gmail_send_email…)
- Le LLM ne peut qu'analyser, raisonner et proposer — sans agir
- Revenir en BUILD avec `Ctrl+T` puis valider le plan

---

## Mémoire projet persistante

Axon dispose de deux couches de contexte projet, séparées et complémentaires.

### `AXON.md` — instructions utilisateur

Crée un fichier `AXON.md` à la racine de n'importe quel projet. Il est détecté automatiquement et injecté dans le system prompt. **Tu l'écris, Axon le lit seulement — jamais modifié.**

```markdown
# AXON.md
- Stack : FastAPI + PostgreSQL + React 18 + TypeScript
- Tests : pytest uniquement, pas de mocks sur la DB
- Conventions : snake_case Python, camelCase TS, pas de `any`
- Ne jamais utiliser `assert` en production
- Les migrations Alembic sont dans `alembic/versions/`
```

### `.axon/memory.md` — mémoire inter-sessions

Axon écrit automatiquement dans ce fichier via l'outil `axon_note` quand il découvre ou fait quelque chose d'important. Le contenu est injecté dans le system prompt de tous les futurs threads sur ce repo.

```
Thread 1 — refactoring auth
  Axon modifie src/auth/tokens.py
  Axon appelle axon_note("Auth migrée vers JWT RS256.
    Clé publique dans config/keys/public.pem.
    Ancien HS256 supprimé de auth/legacy.py.")
  → écrit dans .axon/memory.md

Thread 2 — nouvelle conversation, même repo
  ━━ MÉMOIRE PROJET (sessions précédentes) ━━
  ## 2026-04-22 14:30
  Auth migrée vers JWT RS256. Clé publique dans config/keys/public.pem...

  → Axon sait déjà ce qui s'est passé, sans réexpliquer
```

Axon n'appelle `axon_note` que pour les faits non-évidents : décisions d'architecture, comportements surprenants, contraintes techniques, refactorings majeurs. Pas pour chaque action.

| Fichier | Écrit par | Lu par | Committer ? |
|---------|-----------|--------|-------------|
| `AXON.md` | Toi | Axon | Oui — partagé équipe |
| `.axon/memory.md` | Axon | Axon | Selon préférence |

---

## `@mention` fichiers

Référence directement un fichier dans ton message. Le completer propose les fichiers git-trackés en temps réel (fuzzy search).

```
› regarde @src/agents/jira/tools.py et optimise la fonction _fmt_issue
› compare @src/llm/prompts.py et @configs/base.yaml pour détecter les incohérences
```

- `@` déclenche l'autocomplétion fuzzy sur tous les fichiers du repo
- Tab complète le chemin complet
- À la soumission, le fichier est lu et injecté en bloc de code fencé dans le message
- Tronqué à 6 000 caractères si trop grand, avec indicateur visuel

---

## Autocomplétion slash commands

Dès le premier `/`, un dropdown orange apparaît avec toutes les commandes + description :

```
/ba                → /backend   backend LLM — groq · ollama · ollama_cloud · gemini
/backend g         → groq
/lang              → fr · en · auto
/model             → liste des modèles du backend actif
```

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
   ┌─────────────────────────────────────┐
   │  ✓ Appliquer                        │
   │  ✗ Refuser  →  le LLM en est informé│
   │  ~ Préciser →  feedback → re-génère │
   └─────────────────────────────────────┘
       ↓
6. Vérification auto (build/lint)      ← npm run build · pytest · tsc…
       ↓
7. Résumé final
```

- **`/mode ask`** (défaut) : demande validation à chaque fichier
- **`/mode auto`** : écrit directement sans confirmation
- **`/undo`** : restaure tous les fichiers modifiés depuis le dernier snapshot (avant toute écriture, l'original est sauvegardé en mémoire)
- **`/branch`** : fork le thread actuel pour explorer une approche différente sans perdre l'historique

---

## `/branch` — Fork de conversation

```
› /branch
  branche créée : a1b2c3d4 → e5f6g7h8
```

Crée un nouveau thread en copiant l'état complet de la conversation actuelle. Utile pour :
- Tester une approche différente après un `/undo`
- Comparer deux stratégies de code en parallèle
- Garder une trace propre de chaque tentative

---

## Agents & outils

### Recherche & information
| Outil | Description |
|-------|-------------|
| `web_research_report` | Recherche web approfondie via Tavily |
| `web_search_news` | Actualités récentes (day/week/month) |
| `arxiv_search` · `arxiv_get_paper` | Papers académiques |
| `get_weather_by_city` | Météo en temps réel |
| `get_current_time` | Date et heure |

### Fichiers locaux
| Outil | Description |
|-------|-------------|
| `local_find_file` | Trouver un fichier par nom/pattern |
| `local_list_directory` | Lister un répertoire |
| `local_read_file` | Lire le contenu d'un fichier |
| `local_grep` | Recherche regex dans les fichiers |
| `local_glob` | Glob de fichiers par pattern |

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
| `git_add` · `git_commit` | Staging et commit |
| `git_checkout` · `git_stash` | Branches et stash |
| `git_suggest_commit` | Suggestion de message de commit |
| `url_fetch` | Fetch d'une URL distante |

### Google Workspace
| Outil | Description |
|-------|-------------|
| `gmail_search` · `gmail_summarize` | Lire les emails |
| `gmail_send_email` · `gmail_edit_draft` · `gmail_confirm_send` | Envoyer (HITL) |
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
| `jira_create_issue` | Créer un ticket (Task, Story, Bug, Epic, Subtask) |
| `jira_create_issues_bulk` | Créer plusieurs tickets en masse avec hiérarchie Epic→Story→Task |
| `jira_assign_issue` | Assigner à soi ou à quelqu'un |
| `jira_update_issue` | Modifier titre, description, priorité |
| `jira_transition_issue` | Changer le statut (To Do → In Progress → Done) |
| `jira_add_comment` | Commenter un ticket |
| `jira_get_issue_comments` | Lire les commentaires |
| `jira_get_workload` | Répartition des tickets par membre |
| `jira_search_users` | Trouver un utilisateur par nom |
| `jira_move_issue` · `jira_delete_issue` · `jira_link_to_epic` | Gestion avancée |

### Agent de code (HITL)
| Outil | Description |
|-------|-------------|
| `run_coding_agent` | Délègue au spécialiste de code |
| `dev_plan_create` | Crée un plan d'exécution |
| `dev_plan_step_done` | Valide une étape |
| `dev_explain` | Présente l'analyse à l'utilisateur |
| `propose_file_change` | Propose une modification (diff + approbation HITL) |
| `find_git_repos` | Trouve les repos git locaux |

### Mémoire projet
| Outil | Description |
|-------|-------------|
| `axon_note` | Persiste un fait important dans `.axon/memory.md` — disponible dans les futurs threads |

---

## Commandes

| Commande | Description |
|----------|-------------|
| `/attach` | Joindre un fichier (code, texte, PDF, image) |
| `/paste` | Coller depuis le presse-papiers |
| `/attachments` | Lister les pièces jointes |
| `/detach [fichier]` | Supprimer une pièce jointe (ou toutes) |
| `/letter` | Générer une lettre de motivation (CV + offre) |
| `/upgrade` | Améliorer une lettre existante |
| `/backend <b>` | Changer de backend : `gemini` · `groq` · `ollama` · `ollama_cloud` |
| `/model <nom>` | Changer de modèle (picker interactif si sans argument) |
| `/temp <val>` | Changer la température (ex: `/temp 0.7`) |
| `/mode <ask\|auto>` | Mode édition fichiers — ask (validation) / auto (direct) |
| `/lang <fr\|en\|auto>` | Forcer la langue de réponse |
| `/new` | Nouveau thread |
| `/history` | Lister les threads passés et en reprendre un (flèches ↑↓) |
| `/branch` | Fork le thread actuel pour explorer une autre piste |
| `/undo` | Restaurer tous les fichiers modifiés depuis le dernier round de code |
| `/save` | Sauvegarder le transcript de la session |
| `/config` | Afficher la configuration courante |
| `/debug` | Activer/désactiver le mode debug |
| `/dump` | Afficher tous les messages du thread |
| `q` · `exit` | Quitter |

### Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| `Ctrl+T` | Basculer le mode plan (lecture seule) |
| `Ctrl+O` | Attacher un fichier (= `/attach`) |
| `Ctrl+P` | Coller une image (= `/paste`) |
| `@fichier` + `Tab` | Injecter un fichier dans le message (fuzzy search) |
| `↑` / `↓` | Naviguer dans l'historique des messages |

---

## ToolRetriever — sélection sémantique

À chaque requête, seuls les k=7 outils pertinents sont injectés dans le contexte :

```
Requête → OllamaEmbeddings (nomic-embed-text) → Chroma vectorstore → top-k outils
                                                        ↓
                                              Expansion par groupes
                                              (git détecté → tous les outils git)
                                              (plan mode → write tools filtrés)
```

**Multi-vector anchors** : les méta-outils abstraits (`run_coding_agent`) sont indexés avec plusieurs formulations sémantiques couvrant différentes intentions utilisateur. Une requête comme *"va dans mon repo et refais l'UI"* sélectionne toujours `run_coding_agent` même si les mots-clés ne matchent pas directement.

**Économie typique** : ~40 outils disponibles → 7 envoyés au LLM = ~80 % de tokens système économisés sur la description des outils.

---

## Configuration

### Variables d'environnement (`.env`)

```env
# Identité
USER_NAME=Prénom Nom

# LLM — au moins un requis
GEMINI_API_KEY=AIzaSy...          # Gratuit — https://aistudio.google.com/apikey
GROQ_API_KEY=gsk_...              # https://console.groq.com
OLLAMA_API_KEY=ollama_...         # Optionnel (Ollama Cloud avec compte)
OLLAMA_HOST=http://127.0.0.1:11434

# Recherche web
TAVILY_API_KEY=tvly-...

# Slack
SLACK_USER_TOKEN=xoxp-...

# Jira
JIRA_URL=https://ton-domaine.atlassian.net
JIRA_EMAIL=ton@email.com
JIRA_API_KEY=ATATT3x...

# Divers
PROJECTS_DIR=/home/user/projets    # Accélère find_git_repos (optionnel)
APP_ENV=dev
```

Google (Gmail · Calendar · Drive · Docs · Slides) utilise OAuth2 via `gcp-oauth.keys.json` — voir `bash setup.sh --config-only`.

### `configs/base.yaml`

```yaml
llm_backend: "gemini"              # gemini | ollama | ollama_cloud | groq

ollama:
  model: "qwen2.5:7b"
  temperature: 0.0

groq:
  model: "llama-3.3-70b-versatile"

coding_model: "gemini-2.5-flash"  # Modèle pour le coding specialist

search:
  backend: "tavily"
  max_results: 10
```

### Modèles Ollama (si backend local)

```bash
ollama pull nomic-embed-text    # Obligatoire (ToolRetriever)
ollama pull qwen2.5:7b          # Backend local (optionnel)
```

---

## Structure du projet

```
ai-agent/
├── install.sh                     # Installateur one-line (curl)
├── setup.sh                       # Déploiement interactif (config Gemini incluse)
├── Makefile
├── requirements.txt
├── .env.sample
├── AXON.md                        # (à créer) Contexte projet auto-injecté
├── configs/
│   └── base.yaml
│
└── src/
    ├── ui/
    │   ├── app.py                 # Entrypoint CLI
    │   ├── streaming.py           # Stream LLM · @mention · séparateur
    │   ├── commands.py            # Handler /slash · /branch · /undo · /history
    │   ├── completer.py           # Autocomplétion /commands et @fichiers
    │   ├── plan_mode.py           # État mode plan (Ctrl+T)
    │   ├── panels.py              # Composants Rich
    │   ├── attachments.py         # Fichiers, images, PDF
    │   ├── review.py              # UI review des diffs + HITL email
    │   ├── picker.py              # Sélecteur interactif flèches
    │   ├── edit_mode.py           # Mode ask / auto
    │   ├── token_gauge.py         # Jauge contexte (○◔◑◕●)
    │   ├── prompt_guard.py        # Détection extraction prompt
    │   └── transcript.py          # Sauvegarde conversations
    │
    ├── orchestrator/
    │   ├── graph.py               # LangGraph · CachedToolNode · compression
    │   ├── registry.py            # Enregistrement de tous les outils
    │   ├── state.py               # GlobalState TypedDict
    │   └── tool_retriever.py      # Sélection sémantique (Chroma + anchors)
    │
    ├── llm/
    │   ├── models.py              # Factories LLM (Ollama · Groq · Gemini)
    │   └── prompts.py             # Prompt adaptatif · AXON.md · mode plan
    │
    ├── infra/
    │   ├── settings.py            # Configuration Pydantic
    │   ├── checkpoint.py          # Checkpointer LangGraph (SQLite)
    │   ├── tools_cache.py         # Cache session outils (TTL + invalidation)
    │   ├── redactor.py            # Redaction données sensibles (backends cloud)
    │   └── google_auth.py         # OAuth Google
    │
    └── agents/
        ├── coding/
        │   ├── specialist.py      # Loop LLM spécialiste (HITL)
        │   ├── tools.py           # dev_plan · propose_file_change · dev_explain
        │   └── pending.py         # SnapshotStore + file de changements
        ├── gmail/ · google_calendar/ · google_drive/
        ├── google_doc/ · google_slide/ · google_sheet/
        ├── jira/
        ├── slack/ · shell/ · git/ · filesystem/
        ├── system/ · arxiv/ · time/ · weather/ · search/
        └── image/ · email/
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
