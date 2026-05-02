"""Stack detector — scans manifest files and returns 1 to 4 detected stacks."""
from __future__ import annotations

import json
from pathlib import Path

_MAX_STACKS = 4

# (manifest filename, stack id, confidence score)
# Higher score = picked first when capping at _MAX_STACKS
_MANIFEST_RULES: list[tuple[str, str, int]] = [
    ("Cargo.toml",          "rust",         10),
    ("go.mod",              "go",           10),
    ("pom.xml",             "java",         10),
    ("build.gradle.kts",    "java",         9),
    ("build.gradle",        "java",         9),
    ("CMakeLists.txt",      "systems",      9),
    ("pyproject.toml",      "python",       9),
    ("uv.lock",             "python",       8),
    ("setup.py",            "python",       7),
    ("requirements.txt",    "python",       6),
    # package.json handled separately (frontend vs node_backend vs both)
]

_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", "target", "dist", "build",
    ".git", ".venv", "venv", ".mypy_cache", ".pytest_cache",
})

_FRONTEND_MARKERS = frozenset({
    "react", "next", "@angular/core", "vue", "@vue/core",
    "svelte", "@sveltejs/kit", "nuxt", "gatsby", "remix",
    "@remix-run/react", "solid-js", "preact",
})

_BACKEND_MARKERS = frozenset({
    "express", "@nestjs/core", "fastify", "koa",
    "@hapi/hapi", "hapi", "moleculer", "feathers",
})


def _stacks_from_package_json(path: Path) -> list[tuple[str, int]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return [("node_backend", 6)]

    deps: set[str] = set()
    deps.update(data.get("dependencies", {}).keys())
    deps.update(data.get("devDependencies", {}).keys())

    results: list[tuple[str, int]] = []
    if deps & _FRONTEND_MARKERS:
        results.append(("frontend", 8))
    if deps & _BACKEND_MARKERS:
        results.append(("node_backend", 8))
    if not results:
        # package.json present but no recognized framework
        results.append(("node_backend", 5))
    return results


def _scan_dir(directory: Path, depth_penalty: int = 0) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []

    for filename, stack, score in _MANIFEST_RULES:
        if (directory / filename).exists():
            results.append((stack, score - depth_penalty))

    pkg = directory / "package.json"
    if pkg.exists():
        for stack, score in _stacks_from_package_json(pkg):
            results.append((stack, score - depth_penalty))

    return results


def detect_stacks(
    extra_roots: list[str | Path] | None = None,
    _roots_override: list[str | Path] | None = None,
) -> list[str]:
    """
    Scan the shell's cwd + process cwd + extra_roots for manifest files.
    Also scans direct subdirectories (depth 1) with a reduced confidence score.
    Returns 1–4 stack names ordered by confidence. Empty list if nothing found.

    _roots_override: if provided, skip auto-detection and only scan these roots.
                     Intended for unit tests that need fully isolated scans.
    """
    if _roots_override is not None:
        roots = [Path(r).resolve() for r in _roots_override]
    else:
        roots: list[Path] = []

        # Shell's current working directory (set by shell_cd)
        try:
            from src.agents.shell.tools import _cwd as shell_cwd
            roots.append(Path(shell_cwd).resolve())
        except Exception:
            pass

        # Process cwd
        roots.append(Path.cwd().resolve())

        if extra_roots:
            for r in extra_roots:
                roots.append(Path(r).resolve())

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique_roots: list[Path] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            unique_roots.append(r)

    # Collect (stack, confidence) across all scan points
    raw: list[tuple[str, int]] = []

    for root in unique_roots:
        if not root.exists():
            continue
        # Root level: no penalty
        raw.extend(_scan_dir(root, depth_penalty=0))
        # Direct subdirectories: -2 penalty
        try:
            for sub in sorted(root.iterdir()):
                if sub.is_dir() and sub.name not in _SKIP_DIRS and not sub.name.startswith("."):
                    raw.extend(_scan_dir(sub, depth_penalty=2))
        except PermissionError:
            pass

    if not raw:
        return []

    # Keep highest confidence per stack, then sort and cap
    best: dict[str, int] = {}
    for stack, score in raw:
        if stack not in best or score > best[stack]:
            best[stack] = score

    ordered = sorted(best.items(), key=lambda x: -x[1])
    return [stack for stack, _ in ordered[:_MAX_STACKS]]
