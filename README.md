<div align="center">

<img src="assets/banner.svg" alt="Axon" width="800"/>

<br/>

![Python](https://img.shields.io/badge/Python-3.11+-orange?style=flat-square&logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-blue?style=flat-square)
![Ollama](https://img.shields.io/badge/Ollama-local%20%2B%20cloud-black?style=flat-square)
![Gemini](https://img.shields.io/badge/Gemini-2.0%20Flash-4285F4?style=flat-square&logo=google)
![Tests](https://img.shields.io/badge/tests-363%20passing-brightgreen?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

</div>

---

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/kaiiine/ai-agent/main/install.sh | sh
```

> Clones the repo, installs dependencies, configures APIs, downloads Ollama models, installs Playwright, and creates a global `axon` alias.

```bash
# Or manually:
git clone https://github.com/kaiiine/ai-agent.git && cd ai-agent && bash setup.sh

# Reconfigure integrations without reinstalling:
bash setup.sh --config-only
```

**Requirements:** Python 3.11+ · [Ollama](https://ollama.com/download)

---

## Quick start

```bash
axon
```

```
·············································· ○ 0% ···············································
› Summarize my unread emails
› Go to my project X and fix the bug in auth.ts
› Search for papers on hybrid RAGs on arxiv
› /attach lecture.pdf  then  /fiche
› look at @src/agents/jira/tools.py and optimize _fmt_issue
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
│                       Orchestrator (LangGraph)                       │
│   Semantic ToolRetriever (nomic-embed-text) → k=7 tools             │
│   CachedToolNode (TTL + invalidation) · Cloud redaction             │
│   Proactive context compression (85% → summarize or prune)          │
└─────────────────────────────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────────┐
          │                  │                      │
   ┌──────▼──┐     ┌─────────▼───────┐    ┌────────▼───────────────┐
   │ Agents  │     │  Shell / Git    │    │  Coding Specialist     │
   │ Google  │     │  Filesystem     │    │  Dedicated LLM + HITL  │
   │ Slack   │     │  System         │    │  propose_file_change   │
   │ Jira    │     └─────────────────┘    │  SnapshotStore (/undo) │
   │ Arxiv…  │                            └────────────────────────┘
   └─────────┘
```

---

## LLM Backends

Switchable on the fly via `/backend` or in `configs/base.yaml`:

| Backend | Default model | Context | Notes |
|---------|---------------|---------|-------|
| `ollama_cloud` | `kimi-k2:1t-cloud` | 128 000 | **Recommended** — very powerful |
| `gemini` | `gemini-2.0-flash` | **1 000 000** | Free, massive context window |
| `groq` | `llama-3.3-70b-versatile` | 131 072 | Fast, Groq API |
| `ollama` | `qwen2.5:7b` | 131 072 | 100% local (GPU) |

---

## Features

### Coding agent — HITL

Every file modification follows a strict human-in-the-loop workflow:

```
dev_plan_create → analysis → dev_explain → propose_file_change
                                                ↓
                                   ✓ Apply / ✗ Reject / ~ Refine
                                                ↓
                                   Auto-verification (build/lint/tests)
```

- **`/mode ask`** (default): approval required for each file
- **`/mode auto`**: writes directly without confirmation
- **`/undo`**: restores all files modified since the last round (automatic snapshot)
- Auto language detection: TypeScript/React, Python, Go, Rust, Java, Node.js, systems

### Study sheets & exercises

```bash
› /attach lecture-security.pdf
› /fiche          # → fiche_lecture-security.html (opens in browser)
› /exo            # → interactive MCQ + open questions

# Or in natural language with an attached PDF:
› /attach lecture.pdf
› make me a complete study sheet from this
```

- **`/fiche`**: single-page HTML sheet covering all concepts, formulas, tables, pitfalls and summary
- **`/exo`**: interactive exercises with instant MCQ feedback, open questions, final score, replay button
- Axon Slate Glass design: glassmorphism, dark/light toggle in header, light (parchment) mode by default
- Filename generated from the attached PDF name, native print support (`window.print()`)
- Auto-detection: writing "sheet" / "study" with an attached PDF triggers `/fiche` automatically

### Plan mode (`Ctrl+T`)

Switches to read-only — all write tools are removed. The LLM analyses, reasons and proposes without acting. Switch back to BUILD with `Ctrl+T`.

```
·············· ◆ PLAN ················
 PLAN   Analyse my project and propose an auth architecture refactor
```

### Persistent project memory

**`AXON.md`** — user instructions injected into the system prompt of every thread on this repo. You write it, Axon reads it.

```markdown
# AXON.md
- Stack: FastAPI + PostgreSQL + React 18 + TypeScript
- Tests: pytest only, no DB mocks
- Never use `assert` in production
```

**`.axon/memory.md`** — Axon writes here automatically via `axon_note` when it makes a significant change (architecture decision, major refactor…). Injected into all future threads on this repo.

### `@mention` files

```
› look at @src/agents/jira/tools.py and optimize _fmt_issue
```

`@` triggers fuzzy autocomplete over all git-tracked files. On submit, the file is read and injected into the message.

### Excalidraw diagrams

```
› Create an architecture diagram of my FastAPI app with Redis and PostgreSQL
```

Generates architecture diagrams, flowcharts, mind maps, UML sequences… with optional SVG export for web integration.

---

## Agents & integrations

| Category | Tools |
|----------|-------|
| **Search** | Tavily web search, Tavily research report, Arxiv, weather, translation |
| **Local files** | find, list, read, grep, glob |
| **Shell & System** | shell_run, fuzzy navigation, clipboard, screenshot, processes |
| **Git** | status, log, diff, add, commit, stash, checkout, suggest_commit |
| **Google Workspace** | Gmail (HITL), Calendar, Drive, Docs, Slides |
| **Slack** | read channels/DMs, send (HITL), search |
| **Jira** | read, create, transitions, bulk (Epic→Story→Task), workload |
| **Code** | coding specialist HITL, plan, propose_file_change, download_asset |
| **Visuals** | Excalidraw (diagrams), `/fiche`, `/exo` (HTML sheets) |

---

## Commands

| Command | Description |
|---------|-------------|
| `/attach` | Attach a file (code, text, PDF, image) |
| `/paste` | Paste from clipboard |
| `/attachments` | List pending attachments |
| `/detach [file]` | Remove an attachment (or all) |
| `/fiche` | Generate an HTML study sheet from attached PDFs |
| `/exo` | Generate interactive exercises from attached PDFs |
| `/letter` | Generate a cover letter (CV + job offer) |
| `/upgrade` | Improve an existing letter |
| `/backend <b>` | Switch backend: `gemini` · `groq` · `ollama` · `ollama_cloud` |
| `/model <name>` | Change model (interactive picker if no argument) |
| `/temp <val>` | Change temperature (e.g. `/temp 0.7`) |
| `/mode <ask\|auto>` | File edit mode — ask (approval) / auto (direct) |
| `/lang <fr\|en\|auto>` | Force response language |
| `/new` | Start a new thread |
| `/history` | List past threads and resume one |
| `/branch` | Fork the current thread to explore another approach |
| `/undo` | Restore all files modified since the last round |
| `/save` | Save the session transcript |
| `/config` | Show current configuration |
| `/debug` | Toggle debug mode |
| `q` · `exit` | Quit |

### Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+T` | Toggle plan mode (read-only) |
| `Ctrl+O` | Attach a file (= `/attach`) |
| `Ctrl+P` | Paste an image (= `/paste`) |
| `@file` + `Tab` | Inject a file into the message (fuzzy search) |
| `↑` / `↓` | Navigate message history |

---

## Configuration

### Environment variables (`.env`)

```env
# Identity
USER_NAME=First Last

# LLM — at least one required
GEMINI_API_KEY=AIzaSy...          # Free — https://aistudio.google.com/apikey
GROQ_API_KEY=gsk_...              # https://console.groq.com
OLLAMA_API_KEY=ollama_...         # Optional (Ollama Cloud)
OLLAMA_HOST=http://127.0.0.1:11434

# Web search
TAVILY_API_KEY=tvly-...

# Slack
SLACK_USER_TOKEN=xoxp-...

# Jira
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your@email.com
JIRA_API_KEY=ATATT3x...

# Misc
PROJECTS_DIR=/home/user/projects   # Speeds up find_git_repos (optional)
```

Google (Gmail · Calendar · Drive · Docs · Slides) uses OAuth2 via `gcp-oauth.keys.json` — see `bash setup.sh --config-only`.

### `configs/base.yaml`

```yaml
llm_backend: "ollama_cloud"        # gemini | ollama | ollama_cloud | groq

ollama:
  model: "qwen2.5:7b"
  temperature: 0.0

groq:
  model: "llama-3.3-70b-versatile"

coding_model: "gemini-2.5-flash"   # Model for the coding specialist

search:
  backend: "tavily"
  max_results: 10
```

### Ollama models (if using local backend)

```bash
ollama pull nomic-embed-text    # Required (semantic tool selection)
ollama pull qwen2.5:7b          # Local backend (optional)
```

---

## Tests

```bash
venv/bin/python -m pytest test/ -q   # 363 tests
```

---

## Project structure

```
ai-agent/
├── install.sh / setup.sh          # Installation & configuration
├── configs/base.yaml
├── .env.sample
├── AXON.md                        # (create this) Auto-injected project context
│
└── src/
    ├── ui/                        # Terminal (streaming, commands, completer, attachments)
    ├── orchestrator/              # LangGraph graph, tool registry, tool retriever
    ├── llm/                       # LLM factories, adaptive prompt
    ├── infra/                     # Settings, cache, redactor, browser, auth
    └── agents/
        ├── coding/                # HITL specialist, propose_file_change, per-language prompts
        ├── excalidraw/            # Diagram generation
        ├── study/                 # HTML study sheets & exercises
        ├── gmail/ · google_calendar/ · google_drive/ · google_doc/ · google_slide/
        ├── jira/ · slack/
        └── shell/ · git/ · filesystem/ · system/ · search/ · arxiv/ · weather/
```

---

<div align="center">

Made with ♥ by [@kaiiine](https://github.com/kaiiine)

</div>
