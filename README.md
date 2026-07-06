<div align="center">

<img src="assets/banner.svg" alt="Axon" width="800"/>

<br/>

![Python](https://img.shields.io/badge/Python-3.11+-orange?style=flat-square&logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-blue?style=flat-square)
![Ollama](https://img.shields.io/badge/Ollama-local%20%2B%20cloud-black?style=flat-square)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-4285F4?style=flat-square&logo=google)
![Mistral](https://img.shields.io/badge/Mistral-small%202603-FF7000?style=flat-square)
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
› /build my-project
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
│   Key pool rotation (multi-account, auto-fallback across providers) │
└─────────────────────────────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────────┐
          │                  │                      │
   ┌──────▼──┐     ┌─────────▼───────┐    ┌────────▼───────────────┐
   │ Agents  │     │  Shell / Git    │    │  Coding Specialist     │
   │ Google  │     │  Filesystem     │    │  Dedicated LLM + HITL  │
   │ Slack   │     │  System         │    │  propose_file_change   │
   │ Jira    │     └─────────────────┘    │  Phase-based /build    │
   │ Arxiv…  │                            │  SnapshotStore (/undo) │
   └─────────┘                            └────────────────────────┘
```

---

## LLM Backends

Switchable on the fly via `/backend` or in `configs/base.yaml`:

| Backend | Default model | Context | Notes |
|---------|---------------|---------|-------|
| `ollama_cloud` | `minimax-m2.5:cloud` | 128 000 | **Recommended** — powerful, multi-account pool |
| `gemini` | `gemini-2.5-flash` | **1 000 000** | Free, massive context window |
| `mistral` | `mistral-small-2603` | 128 000 | Free tier, 1M context |
| `ollama` | `qwen2.5:7b` | 131 072 | 100% local (GPU) |

### Multi-key rotation

Axon cycles through all your API keys automatically — within a provider before switching to the next:

```env
OLLAMA_CLOUD_API_KEYS=key1,key2,key3,key4,key5   # exhausted in order
GEMINI_API_KEYS=key1,key2,key3
MISTRAL_API_KEY=key1
FALLBACK_ORDER=ollama_cloud,gemini,mistral        # configurable
```

On 429: key1 → key2 → … → keyN → switch to next provider. Cooldown state persisted in `~/.axon/key_pool_state.json`.

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
- **Per-stack skills**: Next.js · Angular · Vue · Svelte · Three.js · Python · Rust · Go · Node.js · Java · Systems — loaded automatically by manifest detection or via `load_skill()`
- **Task enrichment**: repos and files mentioned in the task are pre-read before the LLM starts
- **Semantic tool selection**: only the 6 most relevant tools are exposed per turn (Chroma embeddings)

### `/build` — Phase-based project builder

Builds an entire project from a `spec.md` by splitting it into independent phases, each run as a separate specialist session. Avoids context overflow on large projects.

```bash
› /build my-project    # reads ~/Documents/projets-perso/my-project/spec.md
```

Each phase is retried on failure. Progress streams live. Token budget is auto-tuned per backend.

### Persistent project memory

**`AXON.md`** — user instructions injected into the system prompt of every thread on this repo.

```markdown
# AXON.md
- Stack: FastAPI + PostgreSQL + React 18 + TypeScript
- Tests: pytest only, no DB mocks
```

**`.axon/memory/`** — Axon writes here automatically after each session:

| File | Content |
|------|---------|
| `journal.md` | Session log (task, tools used, result) |
| `decisions.md` | Architecture decisions with rationale |
| `learnings.md` | Technical discoveries |
| `blockers.md` | Recurring errors and their fixes |
| `evals.md` | Code quality assessments |

Injected into future sessions on the same repo. Browsable in Obsidian (auto-config generated).

### Study sheets & exercises

```bash
› /attach lecture-security.pdf
› /fiche          # → fiche_lecture-security.html (opens in browser)
› /exo            # → interactive MCQ + open questions
```

- **`/fiche`**: single-page HTML covering all concepts, formulas, tables, pitfalls and summary
- **`/exo`**: interactive exercises with instant feedback, final score, replay
- Auto-detection: writing "sheet" / "study" with an attached PDF triggers `/fiche`

### Presentations & slides

```bash
› Create a presentation on microservices architecture
```

Generates professional Reveal.js (HTML) slides with alternating dark/light theme. Export to PPTX available if `python-pptx` is installed.

### Plan mode (`Ctrl+T`)

Switches to read-only — all write tools removed. The LLM analyses and proposes without acting.

```
·············· ◆ PLAN ················
 PLAN   Analyse my project and propose an auth architecture refactor
```

### `@mention` files

```
› look at @src/agents/jira/tools.py and optimize _fmt_issue
```

`@` triggers fuzzy autocomplete over all git-tracked files. On submit, the file is read and injected into the message.

### Mermaid diagrams

Generates flowcharts, sequence diagrams, class diagrams, ER diagrams, C4 containers — rendered as self-contained HTML exported to `public/diagrams/`.

### Jupyter notebooks

Native notebook editing: reads cells with indices, edits cell-by-cell with HITL review, inserts new cells, runs and checks outputs. Never corrupts `.ipynb` JSON.

---

## IDE integration (Zed, Cursor, Continue.dev)

Axon exposes two independent servers for IDE use:

### MCP server — tools for any LLM

Exposes all Axon tools (filesystem, git, shell, search…) to Copilot, Claude, or any MCP-compatible LLM.

```bash
python src/mcp_server.py
```

**Zed** (`~/.config/zed/settings.json`):
```json
"context_servers": {
  "axon": {
    "command": {
      "path": "/path/to/venv/bin/python",
      "args": ["/path/to/ai-agent/src/mcp_server.py"]
    }
  }
}
```

**Claude Desktop** (`~/.config/claude/claude_desktop_config.json`):
```json
"mcpServers": {
  "axon": {
    "command": "/path/to/venv/bin/python",
    "args": ["/path/to/ai-agent/src/mcp_server.py"]
  }
}
```

### API server — Axon as the AI

Makes Axon itself the talking LLM in your IDE (OpenAI-compatible).

```bash
python src/api_server.py    # → http://127.0.0.1:8765/v1
```

**Zed** (`~/.config/zed/settings.json`):
```json
"language_models": {
  "openai": {
    "api_url": "http://127.0.0.1:8765/v1",
    "available_models": [
      {"name": "axon", "max_tokens": 128000, "max_output_tokens": 8192}
    ]
  }
}
```

**Continue.dev** (`config.json`):
```json
{"models": [{"title": "Axon", "provider": "openai", "model": "axon",
             "apiBase": "http://127.0.0.1:8765/v1", "apiKey": "axon"}]}
```

Slash commands available from Zed (prefix with a space to bypass Zed's own `/` picker):
` /keys` · ` /backend gemini` · ` /model` · ` /graph` · ` /build project` · ` /help`

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
| **Code** | coding specialist HITL, plan, propose_file_change, /build phases |
| **Notebooks** | notebook_read, notebook_edit_cell, notebook_insert_cell, notebook_run |
| **Visuals** | Mermaid (diagrams → HTML), slides (Reveal.js + PPTX), /fiche, /exo |

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
| `/spec` | Interactive wizard to generate a `spec.md` for a new project |
| `/build <project>` | Build a project phase by phase from its `spec.md` |
| `/backend <b>` | Switch backend: `gemini` · `ollama` · `ollama_cloud` · `mistral` |
| `/model <name>` | Change model (interactive picker if no argument) |
| `/temp <val>` | Change temperature (e.g. `/temp 0.7`) |
| `/mode <ask\|auto>` | File edit mode — ask (approval) / auto (direct) |
| `/lang <fr\|en\|auto>` | Force response language |
| `/keys` | Show API key pool status (provider, health, cooldown) |
| `/new` | Start a new thread |
| `/history` | List past threads and resume one |
| `/branch` | Fork the current thread to explore another approach |
| `/compact` | Manually compress the current session context |
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
OLLAMA_API_KEY=key                    # Single Ollama Cloud key
OLLAMA_CLOUD_API_KEYS=k1,k2,k3,k4,k5 # Multi-key pool (auto-rotation)
GEMINI_API_KEY=AIzaSy...              # Free — https://aistudio.google.com/apikey
GEMINI_API_KEYS=k1,k2,k3              # Multi-key pool
MISTRAL_API_KEY=...                   # https://console.mistral.ai
FALLBACK_ORDER=ollama_cloud,gemini,mistral

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
llm_backend: "ollama_cloud"        # gemini | ollama | ollama_cloud | mistral

ollama:
  model: "qwen2.5:7b"
  temperature: 0.0

coding_model: "qwen3-coder-next:cloud"  # coding specialist

gemini:
  model: "gemini-2.5-flash"
  coding_model: "gemini-2.5-flash"

mistral:
  model: "mistral-small-2603"
  coding_model: "codestral-2508"

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
venv/bin/python -m pytest test/ -q
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
    ├── llm/                       # LLM factories, key pool, adaptive prompt
    ├── api/                       # OpenAI-compatible API server (models, streaming, commands)
    ├── api_server.py              # FastAPI entry point (port 8765)
    ├── mcp_server.py              # MCP stdio server (Zed, Claude Desktop, Cursor)
    ├── infra/                     # Settings, cache, redactor, browser, auth
    └── agents/
        ├── coding/                # HITL specialist, /build phases, per-stack skills
        │   └── prompts/           # nextjs · angular · vue · svelte · threedee · python · …
        ├── memory/                # Persistent session memory (.axon/memory/)
        ├── slides/                # Reveal.js + PPTX renderer
        ├── mermaid/               # Diagram generation (flowchart, sequence, ER, C4…)
        ├── notebook/              # Jupyter HITL editing (read/edit/insert/run)
        ├── study/                 # HTML study sheets & exercises
        ├── gmail/ · google_calendar/ · google_drive/ · google_doc/ · google_slide/
        ├── jira/ · slack/
        └── shell/ · git/ · filesystem/ · system/ · search/ · arxiv/ · weather/
```

---

<div align="center">

Made with ♥ by [@kaiiine](https://github.com/kaiiine)

</div>
