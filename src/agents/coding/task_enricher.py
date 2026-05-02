"""
Task enricher — detects repo/file references in the task string, pre-reads them,
and injects their content into the HumanMessage before the LLM is called.

Benefits:
  • LLM sees source content before dev_plan_create → plan includes accurate steps
  • Saves tool-call round-trips (no need to local_read_file what's already injected)
  • Works for absolute paths, ~/... paths, and project names in common directories
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# ── Limits ────────────────────────────────────────────────────────────────────

_MAX_SOURCES      = 3       # cap injected sources to avoid context bloat
_MAX_README_CHARS = 6_000   # README is usually the most useful, keep generous
_MAX_FILE_CHARS   = 5_000   # single file
_MAX_MANIFEST_CHARS = 1_500 # package.json / Cargo.toml etc.
_MAX_TREE_ENTRIES = 40      # directory listing lines

# ── File names ────────────────────────────────────────────────────────────────

_README_NAMES = ("README.md", "readme.md", "README.rst", "README.txt", "README")

_MANIFEST_NAMES = (
    "package.json", "Cargo.toml", "go.mod", "pyproject.toml",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "CMakeLists.txt", "requirements.txt", "uv.lock",
    "composer.json", "Gemfile", "mix.exs",
)

_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", "target", "dist", "build",
    ".git", ".venv", "venv", ".mypy_cache", ".pytest_cache",
})

# ── Project search roots ───────────────────────────────────────────────────────

_PROJECT_ROOTS: list[Path] = [
    p for p in [
        Path.home() / "Documents" / "projets-perso",
        Path.home() / "Documents" / "projects",
        Path.home() / "Projects",
        Path.home() / "projects",
        Path.home() / "dev",
        Path.home() / "code",
        Path.home() / "work",
    ]
    if p.exists()
]


# ── Reference extraction ───────────────────────────────────────────────────────

# Matches explicit file system paths in the task text
_PATH_RE = re.compile(
    r'(?<!\w)'               # not preceded by word char
    r'((?:~|/home/\w+|/[\w._-]+)'  # starts with ~, /home/user, or /abs
    r'(?:/[\w._-]+)+'        # followed by at least one /segment
    r'/?)',                   # optional trailing slash
    re.MULTILINE,
)

# Matches project/repo names mentioned with keywords
_KEYWORD_PATTERNS: list[re.Pattern] = [
    # "dans le repo ai-agent", "in the repo my-app"
    re.compile(
        r'(?:dans|in|from)\s+(?:le\s+)?(?:repo|projet|project|dossier|folder)\s+([\w._-]+)',
        re.IGNORECASE,
    ),
    # "lis le repo ai-agent", "read the project foo"
    re.compile(
        r'(?:lis|lire|consulte|regarde|look\s+at|read|check|scan)\s+'
        r'(?:le\s+)?(?:repo|projet|project|readme|dossier)?\s*(?:de\s+|of\s+)?([\w._-]+)',
        re.IGNORECASE,
    ),
    # "tu trouveras dans ai-agent", "you'll find in my-app"
    re.compile(
        r'(?:trouver[as]*|trouve|find)\s+(?:\w+\s+){0,4}(?:dans|in)\s+(?:le\s+)?([\w._-]+)',
        re.IGNORECASE,
    ),
    # "README de ai-agent", "README du projet foo"
    re.compile(
        r'[Rr][Ee][Aa][Dd][Mm][Ee]\s+(?:d[eu]\s+|of\s+)?(?:le\s+)?(?:repo\s+|projet\s+)?([\w._-]+)',
        re.IGNORECASE,
    ),
    # "basé sur ai-agent", "prends exemple sur foo"
    re.compile(
        r'(?:bas[ée]?\s+sur|référ\w+|example\s+from|inspired\s+by|prends\s+exemple\s+sur)\s+([\w._-]+)',
        re.IGNORECASE,
    ),
]

# Tokens we should never treat as project names
_STOPWORDS = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "the", "a", "an",
    "readme", "fichier", "file", "dossier", "repo", "projet", "project",
    "et", "ou", "and", "or", "si", "besoin", "need", "dans", "in",
    "me", "tu", "il", "elle", "nous", "vous", "ils", "elles",
})


def _extract_references(task: str) -> list[str]:
    """Return all unique repo/file references found in the task, in order."""
    refs: list[str] = []

    # 1. Explicit paths (highest confidence)
    for m in _PATH_RE.finditer(task):
        refs.append(m.group(1))

    # 2. Keyword-based project names
    for pattern in _KEYWORD_PATTERNS:
        for m in pattern.finditer(task):
            name = m.group(1).strip(".,;:'\"!?").strip()
            if len(name) >= 2 and name.lower() not in _STOPWORDS:
                refs.append(name)

    # Deduplicate, preserve order
    seen: set[str] = set()
    result: list[str] = []
    for r in refs:
        key = r.rstrip("/")
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result


# ── Content readers ────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int, label: str = "") -> str:
    if len(text) <= limit:
        return text
    suffix = f"\n…[{label} tronqué à {limit} caractères]" if label else "\n…[tronqué]"
    return text[:limit] + suffix


def _tree(path: Path) -> str:
    """Compact directory listing (top-level, skip noise dirs)."""
    lines: list[str] = []
    try:
        entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        for e in entries:
            if e.name.startswith(".") or e.name in _SKIP_DIRS:
                continue
            icon = "📄" if e.is_file() else "📁"
            lines.append(f"  {icon} {e.name}")
            if len(lines) >= _MAX_TREE_ENTRIES:
                lines.append("  …")
                break
    except PermissionError:
        pass
    return "\n".join(lines)


def _read_file_content(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return _truncate(raw, _MAX_FILE_CHARS, path.name)
    except Exception:
        return None


def _read_repo_content(path: Path) -> Optional[str]:
    """Read README + manifests + directory tree from a repo directory."""
    if not path.is_dir():
        return None

    sections: list[str] = [f"📁 Repo : {path}"]

    # Directory tree
    tree = _tree(path)
    if tree:
        sections.append(f"Structure :\n{tree}")

    # README
    for name in _README_NAMES:
        readme = path / name
        if readme.exists():
            try:
                raw = readme.read_text(encoding="utf-8", errors="replace")
                sections.append(
                    f"{name} :\n```\n{_truncate(raw, _MAX_README_CHARS, name)}\n```"
                )
            except Exception:
                pass
            break

    # Manifests (all found, individually capped)
    for name in _MANIFEST_NAMES:
        manifest = path / name
        if manifest.exists():
            try:
                raw = manifest.read_text(encoding="utf-8", errors="replace")
                sections.append(
                    f"{name} :\n```\n{_truncate(raw, _MAX_MANIFEST_CHARS, name)}\n```"
                )
            except Exception:
                pass

    return "\n\n".join(sections) if len(sections) > 1 else None


# ── Project finder ─────────────────────────────────────────────────────────────

def _find_project_dir(name: str) -> Optional[Path]:
    """Locate a project directory by name (exact, then case-insensitive) in known roots."""
    needle = name.lower()
    for root in _PROJECT_ROOTS:
        # Exact match first
        candidate = root / name
        if candidate.is_dir():
            return candidate
        # Case-insensitive scan
        try:
            for entry in root.iterdir():
                if entry.is_dir() and entry.name.lower() == needle:
                    return entry
        except PermissionError:
            pass
    # Also try in shell's current cwd parent
    try:
        from src.agents.shell.tools import _cwd as shell_cwd
        candidate = Path(shell_cwd).parent / name
        if candidate.is_dir():
            return candidate
    except Exception:
        pass
    return None


# ── Resolution ────────────────────────────────────────────────────────────────

def _resolve(ref: str) -> Optional[tuple[str, str]]:
    """
    Try to resolve a reference string to (label, content).
    Tries: absolute path → expanduser path → project name lookup.
    """
    # 1. Direct path (absolute or ~)
    p = Path(ref).expanduser().resolve()
    if p.is_dir():
        content = _read_repo_content(p)
        if content:
            return str(p), content
    elif p.is_file():
        content = _read_file_content(p)
        if content:
            return str(p), f"📄 {p}\n```\n{content}\n```"

    # 2. Project name lookup
    found = _find_project_dir(ref)
    if found:
        content = _read_repo_content(found)
        if content:
            return str(found), content

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_task(task: str) -> str:
    """
    Parse `task` for repo/file references, pre-read them, and inject their content
    at the top of the returned string.

    The LLM receives the injected content before the task text, so it can include
    accurate "read source X" steps in dev_plan_create — or skip them entirely
    because the content is already available.
    """
    refs = _extract_references(task)
    if not refs:
        return task

    injected: list[str] = []
    seen_paths: set[str] = set()

    for ref in refs:
        if len(injected) >= _MAX_SOURCES:
            break
        resolved = _resolve(ref)
        if resolved:
            label, content = resolved
            if label not in seen_paths:
                seen_paths.add(label)
                injected.append(content)

    if not injected:
        return task

    divider = "━" * 56
    header_lines = [
        "⚠ SOURCES PRÉ-LUES — contenu disponible directement ci-dessous.",
        "  Pas besoin de les relire avec local_read_file.",
        "  Utilise ce contenu pour créer un plan précis dès dev_plan_create.",
        divider,
        "\n\n".join(injected),
        divider,
        "",
        "TÂCHE :",
    ]
    return "\n".join(header_lines) + "\n" + task
