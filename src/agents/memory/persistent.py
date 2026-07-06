"""Axon Memory System — capture automatique de sessions + 5 fichiers spécialisés."""
from __future__ import annotations
import json, re, threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_MEMORY_FILES = ["decisions", "learnings", "blockers", "journal", "evals"]
_MAX_FILE_CHARS = 50_000
_ARCHIVE_ENTRIES = 20

# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_git_root(start: Path) -> Optional[Path]:
    for d in [start, *start.parents]:
        if (d / ".git").exists():
            return d
    return None

def _axon_dir() -> Optional[Path]:
    """Retourne {git_root}/.axon strictement scoped au repo courant (règle 8)."""
    try:
        from src.agents.shell.tools import get_cwd
        cwd = get_cwd()
    except Exception:
        cwd = Path.cwd()
    root = _find_git_root(cwd)
    if root is None:
        return None
    try:
        cwd.relative_to(root)
    except ValueError:
        return None
    return root / ".axon"

def _memory_dir() -> Optional[Path]:
    axon = _axon_dir()
    return (axon / "memory") if axon else None

# ── Obsidian ───────────────────────────────────────────────────────────────────

def _obsidian_available() -> bool:
    import shutil, subprocess
    if shutil.which("obsidian"):
        return True
    try:
        r = subprocess.run(["flatpak", "list", "--app"],
                           capture_output=True, text=True, timeout=3)
        if "obsidian" in r.stdout.lower():
            return True
    except Exception:
        pass
    return (Path.home() / ".config" / "obsidian").exists()

def _generate_obsidian_config(axon_dir: Path) -> None:
    obs = axon_dir / ".obsidian"
    obs.mkdir(parents=True, exist_ok=True)
    (obs / "app.json").write_text(
        '{"legacyEditor":false,"livePreview":true,"defaultViewMode":"source"}',
        encoding="utf-8"
    )
    graph = {
        "collapse-filter": False, "search": "", "showTags": True,
        "showAttachments": False, "hideUnresolved": False, "showOrphans": True,
        "colorGroups": [
            {"query": "path:decisions", "color": {"a": 1, "rgb": 14701138}},
            {"query": "path:learnings", "color": {"a": 1, "rgb": 1662806}},
            {"query": "path:blockers",  "color": {"a": 1, "rgb": 14036940}},
            {"query": "path:journal",   "color": {"a": 1, "rgb": 8421504}},
            {"query": "path:evals",     "color": {"a": 1, "rgb": 16711680}},
        ],
    }
    (obs / "graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
    canvas_dir = obs / "canvas"
    canvas_dir.mkdir(exist_ok=True)
    canvas = {
        "nodes": [
            {"id": "decisions", "type": "file", "file": "memory/decisions.md",
             "x": -300, "y": -200, "width": 200, "height": 60},
            {"id": "learnings", "type": "file", "file": "memory/learnings.md",
             "x": 100, "y": -200, "width": 200, "height": 60},
            {"id": "blockers",  "type": "file", "file": "memory/blockers.md",
             "x": -300, "y": 100, "width": 200, "height": 60},
            {"id": "journal",   "type": "file", "file": "memory/journal.md",
             "x": 100, "y": 100, "width": 200, "height": 60},
            {"id": "evals",     "type": "file", "file": "memory/evals.md",
             "x": -100, "y": 300, "width": 200, "height": 60},
        ],
        "edges": [
            {"id": "e1", "fromNode": "blockers",  "toNode": "learnings"},
            {"id": "e2", "fromNode": "decisions", "toNode": "journal"},
            {"id": "e3", "fromNode": "evals",     "toNode": "learnings"},
        ],
    }
    (canvas_dir / "patterns.canvas").write_text(json.dumps(canvas, indent=2), encoding="utf-8")

# ── Migration ──────────────────────────────────────────────────────────────────

def _migrate_legacy(axon_dir: Path) -> None:
    """Migre .axon/memory.md ou .axon/AXON.md vers le nouveau format."""
    archive = axon_dir / "memory" / "archive"
    for legacy_name in ("memory.md", "AXON.md"):
        p = axon_dir / legacy_name
        if p.is_file():
            archive.mkdir(parents=True, exist_ok=True)
            dest = archive / f"{legacy_name.replace('.md', '')}-migrated.md"
            p.rename(dest)

# ── Écriture ───────────────────────────────────────────────────────────────────

_SECRET_RE = re.compile(
    r'(api[_-]?key|apikey|token|bearer|password|passwd|secret|database_url'
    r'|authorization|cookie|jwt|private[_-]?key)\s*[=:]\s*\S+',
    re.IGNORECASE
)

def _redact(text: str) -> str:
    return _SECRET_RE.sub(r'\1=***REDACTED***', text)

def _similarity(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))

def _is_duplicate(entry_md: str, file_path: Path, threshold: float = 0.85) -> bool:
    if not file_path.exists():
        return False
    existing = file_path.read_text(encoding="utf-8", errors="replace")
    entries = re.split(r'\n(?=## \d{4}-\d{2}-\d{2})', existing)
    for past in entries[:5]:
        if _similarity(entry_md, past) > threshold:
            return True
    return False

def _atomic_write(file_path: Path, content: str) -> None:
    import os
    tmp = file_path.with_suffix(file_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, file_path)

_KIND_MAP = {
    "decision": "decisions", "decisions": "decisions",
    "learning": "learnings", "learnings": "learnings",
    "blocker": "blockers",   "blockers": "blockers",
    "eval": "evals",         "evals": "evals",
    "journal": "journal",
}


def _append_entry(file_path: Path, entry_md: str) -> None:
    """Ajoute en tête de fichier. Atomique, dédupliqué, secrets redactés."""
    entry_md = _redact(entry_md)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if _is_duplicate(entry_md, file_path):
        return

    existing = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

    if len(existing) > _MAX_FILE_CHARS:
        archive = file_path.parent / "archive"
        archive.mkdir(exist_ok=True)
        year = datetime.now().year
        arch_path = archive / f"{file_path.stem}-{year}.md"
        entries = re.split(r'\n(?=## \d{4}-\d{2}-\d{2})', existing)
        kept = entries[:_ARCHIVE_ENTRIES]
        old = entries[_ARCHIVE_ENTRIES:]
        if old:
            with arch_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(old))
        existing = "\n".join(kept)

    if not existing.strip():
        existing = f"# {file_path.stem.capitalize()} — {file_path.parent.parent.parent.name}\n\n"

    h1_end = existing.find("\n\n")
    if h1_end == -1:
        content = existing + "\n" + entry_md
    else:
        content = existing[:h1_end + 2] + entry_md + "\n\n" + existing[h1_end + 2:]

    _atomic_write(file_path, content)


def write_single_entry(kind: str, fact: str) -> str:
    """Utilisé par axon_note() pour écrire dans le bon fichier."""
    mdir = _memory_dir()
    if mdir is None:
        return "Pas de repo git détecté"
    kind = _KIND_MAP.get(kind.lower().strip(), "learnings")
    date_str = datetime.now().strftime("%Y-%m-%d")
    entry = f"## {date_str} — note manuelle\n**{kind.capitalize()}** : {fact.strip()}\n"
    _append_entry(mdir / f"{kind}.md", entry)
    return f"Note enregistrée dans .axon/memory/{kind}.md"

# ── Lecture pour injection ──────────────────────────────────────────────────────

_IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}

def _entry_importance(entry: str) -> str:
    m = re.search(r'\*\*Importance\*\*\s*:\s*(high|medium|low)', entry, re.IGNORECASE)
    return m.group(1).lower() if m else "medium"

def _load_context(n_entries: int = 3, char_budget: int = 6000) -> str:
    """Lit les N dernières entrées prioritaires (high d'abord) — règles 4 & 8."""
    mdir = _memory_dir()
    if mdir is None or not mdir.exists():
        return ""
    sections: list[str] = []
    total_chars = 0
    for name in _MEMORY_FILES:
        p = mdir / f"{name}.md"
        if not p.is_file():
            continue
        content = p.read_text(encoding="utf-8", errors="replace")
        entries = re.split(r'\n(?=## \d{4}-\d{2}-\d{2})', content)
        entries = [e.strip() for e in entries if e.strip().startswith("## ")]
        entries.sort(key=lambda e: (_IMPORTANCE_ORDER.get(_entry_importance(e), 1),))
        filtered = []
        for e in entries[:n_entries]:
            if total_chars + len(e) > char_budget and _entry_importance(e) == "low":
                continue
            filtered.append(e)
            total_chars += len(e)
        if filtered:
            block = "\n\n".join(filtered)
            sections.append(f"### {name.upper()}\n{block}")
    if not sections:
        return ""
    return "━━ AXON MEMORY (sessions précédentes) ━━\n" + "\n\n".join(sections)

# ── Capture automatique (fin de session) ───────────────────────────────────────

_VALID_TAGS = {
    "#arch", "#infra", "#frontend", "#backend", "#perf", "#security",
    "#hallucination", "#tooling", "#ux", "#migration", "#pattern", "#anti-pattern"
}

_SYNTHESIS_PROMPT = """\
Tu analyses une session de coding Axon et extrais UNIQUEMENT ce qui s'est passé réellement.
NE JAMAIS inventer ou généraliser. Une section vide est préférable à une entrée hallucée.
NE JAMAIS inclure de secrets, tokens, API keys, passwords, URLs de base de données.

Format de réponse : JSON uniquement, sans markdown.
{
  "decisions": [
    {
      "title": "titre court",
      "decision": "...", "why": "...", "rejected": "...", "impact": "...",
      "importance": "high|medium|low",
      "confidence": "high|medium|low",
      "tags": ["#arch"],
      "links": ["[[learnings#titre-si-pertinent]]"]
    }
  ],
  "learnings": [
    {
      "title": "titre court",
      "learning": "...", "context": "...", "apply": "...",
      "importance": "high|medium|low",
      "confidence": "high|medium|low",
      "tags": ["#pattern"],
      "links": []
    }
  ],
  "blockers": [
    {
      "title": "titre court",
      "problem": "...", "context": "...", "solution": "...",
      "recurrence": "première fois",
      "importance": "high|medium|low",
      "confidence": "high|medium|low",
      "tags": [],
      "links": ["[[learnings#titre-si-resolution-devient-learning]]"]
    }
  ],
  "evals": [
    {
      "title": "titre court",
      "type": "hallucination|obsolescence|mauvaise décision|faux positif",
      "context": "...", "observed": "...", "expected": "...",
      "impact": "bloquant|mineur|cosmétique",
      "importance": "high|medium|low",
      "confidence": "high|medium|low",
      "tags": ["#hallucination"],
      "links": ["[[decisions#titre-si-décision-liée]]"]
    }
  ]
}

Règles :
- decisions : seulement si propose_file_change sur configs/architecture + raison explicite
- learnings : erreurs corrigées, patterns répétés (>2 fois), surprises dans les résultats
- blockers : shell_run avec exit_code ≠ 0 ET sa résolution ; omets si non résolu
- evals : UNIQUEMENT si l'utilisateur a explicitement corrigé ("c'est faux", "tu t'es trompé"...)
- Sections vides = [] — ne jamais remplir avec du contenu générique
- journal : NE PAS inclure — généré déterministiquement (règle 7)
- links : wikilinks Obsidian cross-fichiers — uniquement si lien réel (règle 6)
- tags : choisir parmi : #arch #infra #frontend #backend #perf #security #hallucination #tooling #ux #migration #pattern #anti-pattern
"""

def _build_deterministic_journal(messages: list, enriched_task: str,
                                  result_text: str) -> str:
    """Journal déterministe sans LLM (règle 7) : tâche + CWD + fichiers modifiés + résultat."""
    from src.agents.shell.tools import get_cwd
    try:
        cwd = str(get_cwd())
    except Exception:
        cwd = "?"
    files_modified = []
    tool_calls_summary = []
    for msg in messages:
        for tc in (getattr(msg, "tool_calls", []) or []):
            name = tc.get("name", "")
            args = tc.get("args", {})
            if name == "propose_file_change":
                f = args.get("path", args.get("file_path", "?"))
                if f not in files_modified:
                    files_modified.append(f)
            elif name in ("shell_run", "dev_explain", "dev_plan_create"):
                tool_calls_summary.append(name)
    files_str = ", ".join(files_modified[:10]) or "aucun"
    tools_str = ", ".join(sorted(set(tool_calls_summary))) or "aucun"
    status = "OK" if "interrompue" not in result_text.lower() else "interrompu"
    return (
        f"**Objectif** : {enriched_task[:200].strip()}\n"
        f"**CWD** : {cwd}\n"
        f"**Fichiers modifiés** : {files_str}\n"
        f"**Outils utilisés** : {tools_str}\n"
        f"**État final** : {status}\n"
        f"**Prochain** : (à compléter manuellement)\n"
    )


def _build_session_summary(messages: list, enriched_task: str, result_text: str) -> str:
    """Construit le résumé compressé de la session à envoyer au LLM."""
    lines = [f"TÂCHE : {enriched_task[:500]}"]
    for msg in messages:
        tcs = getattr(msg, "tool_calls", []) or []
        for tc in tcs:
            name = tc.get("name", "")
            args = tc.get("args", {})
            if name in ("propose_file_change", "shell_run", "dev_explain"):
                lines.append(f"TOOL {name}: {json.dumps(args, ensure_ascii=False)[:300]}")
    lines.append(f"RÉSULTAT : {result_text[:800]}")
    return "\n".join(lines)


def _do_persist(messages: list, enriched_task: str, result_text: str, backend: str,
                axon: "Path | None" = None) -> None:
    """Exécuté dans un thread daemon. Échoue silencieusement."""
    try:
        if axon is None:
            return
        mdir = axon / "memory"
        mdir.mkdir(parents=True, exist_ok=True)
        _migrate_legacy(axon)
        gi = axon / ".gitignore"
        if not gi.exists():
            gi.write_text("# Obsidian local config — do not commit\n.obsidian/\n", encoding="utf-8")
        _generate_obsidian_config(axon)
        if not _obsidian_available():
            sentinel = axon / ".obsidian_noted"
            if not sentinel.exists():
                sentinel.write_text("noted", encoding="utf-8")

        # Journal DÉTERMINISTE en premier — garanti même si LLM échoue
        jp = mdir / "journal.md"
        n_sessions = (jp.read_text(encoding="utf-8").count("## 20") + 1) if jp.exists() else 1
        journal_body = _build_deterministic_journal(messages, enriched_task, result_text)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        journal_entry = (f"## {now_str} — Session #{n_sessions}\n"
                         f"**Importance** : medium | **Confidence** : high\n"
                         + journal_body)
        _append_entry(jp, journal_entry)

        # Appel LLM de synthèse (decisions, learnings, blockers, evals)
        from src.infra.settings import settings
        from src.llm.models import make_llm, make_llm_ollama_cloud, make_llm_groq, make_llm_gemini, make_llm_mistral
        _factories = {
            "groq": make_llm_groq, "ollama_cloud": make_llm_ollama_cloud,
            "gemini": make_llm_gemini, "mistral": make_llm_mistral,
        }
        llm = _factories.get(backend, make_llm_ollama_cloud)()
        from langchain_core.messages import SystemMessage, HumanMessage
        summary = _build_session_summary(messages, enriched_task, result_text)
        resp = llm.invoke([SystemMessage(content=_SYNTHESIS_PROMPT),
                           HumanMessage(content=summary)])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            return
        data = json.loads(m.group())
        date_str = datetime.now().strftime("%Y-%m-%d")

        def _score_line(d: dict) -> str:
            return f"**Importance** : {d.get('importance','medium')} | **Confidence** : {d.get('confidence','medium')}\n"

        def _links_line(d: dict) -> str:
            links = [l for l in d.get("links", []) if l.strip()]
            return (f"**Liens** : {' '.join(links)}\n") if links else ""

        def _tags_line(d: dict) -> str:
            valid = [t for t in d.get("tags", []) if t in _VALID_TAGS]
            return f"**Tags** : {' '.join(valid)}\n" if valid else ""

        for d in (data.get("decisions") or []):
            entry = (f"## {date_str} — {d.get('title','')}\n"
                     + _score_line(d)
                     + f"**Décision** : {d.get('decision','')}\n"
                     f"**Pourquoi** : {d.get('why','')}\n"
                     f"**Alternatives rejetées** : {d.get('rejected','—')}\n"
                     f"**Impact** : {d.get('impact','')}\n"
                     + _tags_line(d) + _links_line(d))
            _append_entry(mdir / "decisions.md", entry)
        for l in (data.get("learnings") or []):
            entry = (f"## {date_str} — {l.get('title','')}\n"
                     + _score_line(l)
                     + f"**Apprentissage** : {l.get('learning','')}\n"
                     f"**Contexte** : {l.get('context','')}\n"
                     f"**À appliquer** : {l.get('apply','')}\n"
                     + _tags_line(l) + _links_line(l))
            _append_entry(mdir / "learnings.md", entry)
        for b in (data.get("blockers") or []):
            entry = (f"## {date_str} — {b.get('title','')}\n"
                     + _score_line(b)
                     + f"**Problème** : {b.get('problem','')}\n"
                     f"**Contexte** : {b.get('context','')}\n"
                     f"**Solution** : {b.get('solution','')}\n"
                     f"**Récurrence** : {b.get('recurrence','première fois')}\n"
                     + _tags_line(b) + _links_line(b))
            _append_entry(mdir / "blockers.md", entry)
        for e in (data.get("evals") or []):
            entry = (f"## {date_str} — {e.get('title','')}\n"
                     + _score_line(e)
                     + f"**Type** : {e.get('type','')}\n"
                     f"**Contexte** : {e.get('context','')}\n"
                     f"**Ce qu'Axon a fait** : {e.get('observed','')}\n"
                     f"**Ce qui était attendu** : {e.get('expected','')}\n"
                     f"**Impact** : {e.get('impact','')}\n"
                     + _tags_line(e) + _links_line(e))
            _append_entry(mdir / "evals.md", entry)
    except Exception:
        pass


def _persist_session_memory(messages: list, enriched_task: str,
                             result_text: str, backend: str) -> None:
    """Lance la persistance en arrière-plan (non-bloquant)."""
    axon = _axon_dir()  # capturé avant le spawn — CWD peut changer dans le thread
    threading.Thread(
        target=_do_persist,
        args=(messages, enriched_task, result_text, backend, axon),
        daemon=True,
    ).start()
