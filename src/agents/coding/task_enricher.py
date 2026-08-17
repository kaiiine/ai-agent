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
        Path.home() / "projets-persos",
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

# Detects standalone filenames mentioned in a task ("script.py", "config.json", etc.)
# but NOT filenames that are already part of an absolute path (handled by _PATH_RE).
_CODE_EXTENSIONS = (
    "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "toml", "sh",
    "go", "rs", "java", "kt", "swift", "rb", "php", "css", "html", "vue",
    "svelte", "md", "txt", "env",
)
_FILENAME_RE = re.compile(
    r"(?<![/\w.])(\w[\w._-]*\.(?:" + "|".join(_CODE_EXTENSIONS) + r"))(?![/\w])",
    re.IGNORECASE,
)


_SPEC_SECTION_RE = re.compile(r'^##\s+\S', re.MULTILINE)
_MIN_SPEC_CHARS = 500
_SPEC_INLINE_LIMIT = 4_000
_SPEC_FILE_PREFIX = "/tmp/axon_spec_"

#: En-tête que `build_runner._inventaire_du_projet()` pose dans une tâche de phase.
#: Sa présence signifie « la surface du projet est déjà décrite ici » — donc que
#: moissonner des noms de fichiers pour les pré-lire serait redondant. Le marqueur
#: est repris littéralement de build_runner ; un test lie les deux pour qu'un
#: renommage d'un côté ne rende pas ce garde-fou muet de l'autre.
_INVENTAIRE_MARQUEUR = "FICHIERS DÉJÀ PRÉSENTS"


def _extract_inline_spec(task: str) -> Optional[tuple[str, str]]:
    """Detect a pasted design brief (≥2 ## sections, ≥500 chars).

    Returns (inline_preview, full_path) or None if no spec detected.
    """
    import hashlib
    matches = list(_SPEC_SECTION_RE.finditer(task))
    if len(matches) < 2:
        return None
    spec = task[matches[0].start():]
    if len(spec) < _MIN_SPEC_CHARS:
        return None
    spec_hash = hashlib.md5(spec.encode()).hexdigest()[:8]
    spec_path = f"{_SPEC_FILE_PREFIX}{spec_hash}.md"
    try:
        Path(spec_path).write_text(spec, encoding="utf-8")
    except Exception:
        spec_path = ""
    label = f"spec — suite dans {spec_path}" if spec_path else "spec"
    preview = _truncate(spec, _SPEC_INLINE_LIMIT, label)
    return preview, spec_path


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
    """Read GRAPH_REPORT.md (preferred) or README + manifests + directory tree from a repo directory."""
    if not path.is_dir():
        return None

    sections: list[str] = [f"📁 Repo : {path}"]

    # Directory tree
    tree = _tree(path)
    if tree:
        sections.append(f"Structure :\n{tree}")

    # GRAPH_REPORT.md — injected with priority when available (replaces README for architecture context)
    # graphify writes output to <project>/graphify-out/ by default
    graph_report = path / "graphify-out" / "GRAPH_REPORT.md"
    if not graph_report.exists():
        graph_report = path / "GRAPH_REPORT.md"  # fallback: root-level
    has_graph_report = False
    if graph_report.exists():
        try:
            raw = graph_report.read_text(encoding="utf-8", errors="replace")
            sections.append(
                f"GRAPH_REPORT.md (architecture complète) :\n```\n{_truncate(raw, _MAX_README_CHARS, 'GRAPH_REPORT.md')}\n```"
            )
            has_graph_report = True
        except Exception:
            pass

    # README — skipped if GRAPH_REPORT.md was injected (avoids duplication)
    # If no GRAPH_REPORT.md, use README as fallback
    if not has_graph_report:
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

def _find_file_in_scope(filename: str) -> Optional[Path]:
    """
    Locate a bare filename (e.g. 'script.py') without a path.
    Search order: cwd → cwd parents (3 levels) → project roots (shallow, depth 4).

    Un nom AMBIGU ne résout rien. La version précédente rendait le PREMIER match
    rencontré, et ce silence-là coûtait cher : `_cwd` vaut `$HOME` par défaut et
    le build ne le déplace jamais — il passe `cwd=` à ses sous-processus, pas à la
    session shell. Une phase construisant un projet voyait donc injecter, sous
    l'en-tête « SOURCES PRÉ-LUES — contenu disponible directement », le
    `Footer.tsx` d'un AUTRE projet du disque, arrivé premier dans le parcours.

    Injecter le mauvais fichier est pire que n'en injecter aucun : l'agent ne peut
    pas savoir qu'il lit le mauvais, alors que rien du tout le laisse lire lui-même
    avec `local_read_file`, où le chemin est explicite. En cas d'homonymie, on se
    taît donc, dans la base où l'ambiguïté apparaît.
    """
    try:
        from src.agents.shell.tools import _cwd as shell_cwd
        bases: list[Path] = []
        cwd = Path(shell_cwd)
        for _ in range(4):  # cwd + 3 parents
            bases.append(cwd)
            if cwd.parent == cwd:
                break
            cwd = cwd.parent
        for root in _PROJECT_ROOTS:
            bases.append(root)

        needle = filename.lower()
        for base in bases:
            trouves: list[Path] = []
            try:
                for p in base.rglob(filename):
                    if p.is_file() and p.name.lower() == needle:
                        # Skip noise dirs
                        parts = set(p.parts)
                        if parts & _SKIP_DIRS:
                            continue
                        trouves.append(p)
                        if len(trouves) > 1:
                            return None      # homonymes : on se taît
                        continue
                    # rglob depth guard: skip deep hits from project roots
                    if base in _PROJECT_ROOTS and len(p.relative_to(base).parts) > 4:
                        break
            except (PermissionError, OSError):
                continue
            if trouves:
                return trouves[0]
    except Exception:
        pass
    return None


def _resolve(ref: str) -> Optional[tuple[str, str]]:
    """
    Try to resolve a reference string to (label, content).
    Tries: absolute path → expanduser path → project name lookup → bare filename.
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

    # 3. Bare filename (e.g. "script.py") — scoped search around cwd
    if "." in ref and "/" not in ref and "\\" not in ref:
        located = _find_file_in_scope(ref)
        if located:
            content = _read_file_content(located)
            if content:
                return str(located), f"📄 {located}\n```\n{content}\n```"

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
    spec_result = _extract_inline_spec(task)

    # Also detect bare filenames (e.g. "script.py", "config.json") not caught by _PATH_RE.
    # Cap at 3 filenames to avoid context bloat; skip if already in refs.
    #
    # Sauf si la tâche PORTE DÉJÀ son inventaire. Une tâche de phase de build liste
    # les fichiers présents avec leurs exports, et dit explicitement de n'en ouvrir
    # un que si son CONTENU est nécessaire. Y pré-lire les noms qu'elle vient de
    # citer défait cet inventaire au lieu de le compléter.
    #
    # Mesuré sur une phase « Pages » réaliste : 2 672 caractères de tâche
    # devenaient 10 872, soit +8 200 (≈ 2 000 tokens) à CHAQUE phase de CHAQUE
    # build. Et les noms moissonnés ne venaient pas tous de l'inventaire —
    # `tailwind.config.js` et `globals.css` étaient récoltés dans l'EXEMPLE de
    # steps du bloc Instructions, où ils n'illustrent qu'une bonne granularité de
    # plan et ne désignent aucun fichier du projet.
    if _INVENTAIRE_MARQUEUR not in task:
        _existing_refs_lower = {r.lower() for r in refs}
        _filename_matches = _FILENAME_RE.findall(task)
        for fname in _filename_matches:
            if len(refs) >= _MAX_SOURCES:
                break
            if fname.lower() not in _existing_refs_lower:
                refs.append(fname)
                _existing_refs_lower.add(fname.lower())

    # When a spec is detected, strip it from task — the spec_prefix carries
    # the preview; keeping the full spec in task would double it in context.
    if spec_result:
        m0 = _SPEC_SECTION_RE.search(task)
        if m0:
            task = task[:m0.start()].strip()

    if not refs and not spec_result:
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

    divider = "━" * 56

    spec_prefix = ""
    if spec_result:
        spec_preview, spec_path = spec_result
        file_note = f"\n  Spec complète : local_read_file('{spec_path}')" if spec_path else ""
        spec_prefix = (
            f"⚠ SPEC PERMANENTE — à préserver en cas de compression.{file_note}\n"
            f"  Modules, textes, palette, contraintes visuelles — copier mot pour mot.\n"
            f"{divider}\n{spec_preview}\n{divider}\n\n"
        )

    if not injected:
        return spec_prefix + task if spec_prefix else task

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
    return spec_prefix + "\n".join(header_lines) + "\n" + task
