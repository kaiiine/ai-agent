from __future__ import annotations

import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Any, List

from langchain_core.tools import tool

_HOME = Path.home()
_MAX_RESULTS = 20
_MAX_FILE_SIZE = 200_000  # 200KB


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _fd_available() -> bool:
    try:
        subprocess.run(["fd", "--version"], capture_output=True, timeout=2)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _search_files(pattern: str, base: str | None = None) -> list[str]:
    """Cherche des fichiers par nom. Utilise fd si dispo, sinon find."""
    base = base or str(_HOME)
    # fd — rapide, respecte .gitignore, ignore automatiquement les dossiers cachés
    if _fd_available():
        result = subprocess.run(
            ["fd", "--type", "f", "--follow", "--max-depth", "10",
             "--exclude", ".git", "--exclude", "node_modules", "--exclude", ".venv",
             "--exclude", "__pycache__", "--exclude", ".cargo", "--exclude", ".rustup",
             pattern, base],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [l for l in result.stdout.strip().split("\n") if l]

    # find — fallback universel
    result = subprocess.run(
        ["find", base, "-type", "f", "-iname", f"*{pattern}*",
         "-not", "-path", "*/.git/*",
         "-not", "-path", "*/node_modules/*",
         "-not", "-path", "*/.venv/*",
         "-not", "-path", "*/__pycache__/*",
         "-not", "-path", "*/.cargo/*",
         "-not", "-path", "*/.rustup/*",
         ],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode == 0:
        return [l for l in result.stdout.strip().split("\n") if l]
    return []


def _search_dirs(pattern: str, base: str | None = None) -> list[str]:
    """Cherche des dossiers par nom. Utilise fd si dispo, sinon find."""
    base = base or str(_HOME)
    if _fd_available():
        result = subprocess.run(
            ["fd", "--type", "d", "--follow", "--max-depth", "8",
             "--exclude", ".git", "--exclude", "node_modules", "--exclude", ".venv",
             pattern, base],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [l for l in result.stdout.strip().split("\n") if l]

    result = subprocess.run(
        ["find", base, "-type", "d", "-iname", f"*{pattern}*",
         "-not", "-path", "*/.git/*",
         "-not", "-path", "*/node_modules/*",
         "-not", "-path", "*/.venv/*",
         ],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode == 0:
        return [l for l in result.stdout.strip().split("\n") if l]
    return []


@tool("local_find_file")
def local_find_file(name: str, root: str = "") -> Dict[str, Any]:
    """
    Recherche un fichier local par nom approximatif, depuis $HOME.
    Utiliser quand l'utilisateur mentionne un nom de fichier local.

    Args:
        name: nom ou fragment du fichier à chercher (approximatif, ex: "cv", "rapport", "budget")
        root: dossier de départ optionnel (chemin absolu)
    Returns:
        {"status": "ok", "matches": [{"path", "name", "size", "ext"}, ...]}
    """
    needle = name.lower().strip()
    # Si root fourni mais invalide → fallback HOME
    if root and not Path(root).exists():
        root = ""
    base = root or str(_HOME)

    raw_paths = _search_files(needle, base)

    # Score et filtre
    scored: list[tuple[float, Path]] = []
    for raw in raw_paths:
        p = Path(raw)
        fname = p.name.lower()
        stem = p.stem.lower()
        if needle in fname:
            score = 1.0
        else:
            score = max(_similarity(needle, stem), _similarity(needle, fname))
        if score >= 0.4:
            scored.append((score, p))

    scored.sort(key=lambda x: -x[0])

    seen: set[str] = set()
    results = []
    for score, p in scored:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        try:
            size = p.stat().st_size
        except OSError:
            continue
        results.append({
            "path": str(p),
            "name": p.name,
            "ext": p.suffix.lower(),
            "size": f"{size // 1024}KB" if size >= 1024 else f"{size}B",
        })
        if len(results) >= _MAX_RESULTS:
            break

    if not results:
        return {"status": "not_found", "matches": []}
    return {"status": "ok", "count": len(results), "matches": results}


@tool("local_list_directory")
def local_list_directory(path: str = "", name: str = "") -> Dict[str, Any]:
    """
    Liste le contenu d'un dossier local.
    Utiliser quand l'utilisateur veut voir les fichiers dans un dossier.
    TOUJOURS utiliser name= pour chercher par nom. Ne jamais inventer un chemin.

    Args:
        path: chemin absolu du dossier si déjà connu
        name: nom approximatif du dossier à trouver (ex: "CV", "Downloads", "projets")
    Returns:
        {"status": "ok", "path": "...", "entries": [...]}
    """
    target: Path | None = None

    if path:
        p = Path(path)
        if p.exists() and p.is_dir():
            target = p
        else:
            # Chemin invalide → extraire le nom et chercher
            name = name or p.name

    if target is None and name:
        needle = name.lower().strip()
        candidates = _search_dirs(needle)

        scored: list[tuple[float, int, Path]] = []
        for raw in candidates:
            d = Path(raw)
            dname = d.name.lower()
            # Score de nom
            if dname == needle:
                name_score = 2.0  # match exact
            elif needle in dname:
                name_score = 1.0
            else:
                name_score = _similarity(needle, dname)
            # Pénalité de profondeur : préférer les chemins courts
            depth = len(d.parts)
            scored.append((name_score, -depth, d))

        if scored:
            # Trier : meilleur score d'abord, puis chemin le plus court
            scored.sort(key=lambda x: (-x[0], x[1]))
            target = scored[0][2]

    if target is None or not target.exists():
        return {"status": "not_found", "error": f"Dossier introuvable : {path or name}"}

    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            if entry.is_dir():
                entries.append({"name": entry.name, "type": "dossier"})
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                entries.append({
                    "name": entry.name,
                    "type": "fichier",
                    "ext": entry.suffix.lower(),
                    "size": f"{size // 1024}KB" if size >= 1024 else f"{size}B",
                    "path": str(entry),
                })
    except PermissionError as e:
        return {"status": "error", "error": str(e)}

    return {"status": "ok", "path": str(target), "count": len(entries), "entries": entries}


@tool("local_read_file")
def local_read_file(path: str) -> Dict[str, Any]:
    """
    Lit le contenu d'un fichier local. Supporte : texte, code, PDF.
    Utiliser après avoir obtenu le chemin via local_find_file ou local_list_directory.

    Args:
        path: chemin absolu du fichier
    Returns:
        {"status": "ok", "name": "...", "content": "...", "lines": N}
    """
    p = Path(path)
    if not p.exists():
        return {"status": "not_found", "path": path, "error": "Fichier introuvable"}
    if not p.is_file():
        return {"status": "error", "error": "Le chemin n'est pas un fichier"}

    size = p.stat().st_size
    ext = p.suffix.lower()

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            pages = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(f"[Page {i + 1}]\n{text}")
            content = "\n\n".join(pages)[:200_000]
            if not content:
                return {"status": "error", "error": "PDF sans texte extractible (scanné ?)"}
            return {
                "status": "ok", "name": p.name, "path": str(p),
                "content": content, "pages": len(reader.pages),
                "size": f"{size // 1024}KB",
            }
        except Exception as e:
            return {"status": "error", "error": f"Erreur lecture PDF: {e}"}

    if size > _MAX_FILE_SIZE:
        return {
            "status": "too_large",
            "name": p.name,
            "size": f"{size // 1024}KB",
            "error": f"Fichier trop grand ({size // 1024}KB > 200KB).",
        }

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return {
            "status": "ok", "name": p.name, "path": str(p),
            "ext": ext, "content": content, "lines": content.count("\n") + 1,
            "size": f"{size // 1024}KB" if size >= 1024 else f"{size}B",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
