from __future__ import annotations

import glob as _glob_mod
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Any, List

from langchain_core.tools import tool

_HOME = Path.home()

from src.utils.paths import get_projects_dir
_MAX_RESULTS     = 20
_MAX_FILE_SIZE   = 200_000   # 200 KB
_MAX_GREP_OUTPUT = 50_000    # 50 K chars
_MAX_GLOB_RESULTS = 100


# ── Internal helpers ──────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _fd_available() -> bool:
    try:
        subprocess.run(["fd", "--version"], capture_output=True, timeout=2)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _rg_available() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, timeout=2)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _search_files(pattern: str, base: str | None = None) -> list[str]:
    base = base or str(_HOME)
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


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool("local_find_file")
def local_find_file(name: str, root: str = "") -> Dict[str, Any]:
    """
    Cherche un fichier local sur le disque par nom approximatif.

    Utilise ce tool quand l'utilisateur veut :
    - trouver un fichier local dont il connaît une partie du nom
    - localiser un document (CV, rapport, facture) sur son ordinateur
    - savoir où est stocké un fichier

    Mots-clés : fichier, trouver fichier, localiser, document local, chercher, CV, PDF, disque

    Args:
        name: nom ou fragment du fichier à chercher (approximatif, ex: "cv", "rapport", "budget")
        root: dossier de départ optionnel (chemin absolu)
    Returns:
        {"status": "ok", "matches": [{"path", "name", "size", "ext"}, ...]}
    """
    needle = name.lower().strip()
    if root and not Path(root).exists():
        root = ""
    base = root or str(_HOME)

    raw_paths = _search_files(needle, base)

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
    Liste le contenu d'un dossier local (fichiers et sous-dossiers).

    Utilise ce tool quand l'utilisateur veut :
    - voir ce qu'il y a dans un dossier
    - explorer l'arborescence d'un répertoire local
    - trouver les fichiers contenus dans un dossier

    Mots-clés : dossier, répertoire, contenu, lister fichiers, explorer, arborescence

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
            name = name or p.name

    if target is None and name:
        needle = name.lower().strip()
        candidates = _search_dirs(needle)

        scored: list[tuple[float, int, Path]] = []
        for raw in candidates:
            d = Path(raw)
            dname = d.name.lower()
            if dname == needle:
                name_score = 2.0
            elif needle in dname:
                name_score = 1.0
            else:
                name_score = _similarity(needle, dname)
            depth = len(d.parts)
            scored.append((name_score, -depth, d))

        if scored:
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
def local_read_file(path: str, offset: int = 0, limit: int = 0) -> Dict[str, Any]:
    """
    Lit et retourne le contenu textuel d'un fichier local (texte, code, PDF).

    Utilise ce tool quand l'utilisateur veut :
    - lire le contenu d'un fichier local
    - voir le code source d'un fichier
    - ouvrir et analyser un document texte ou PDF local

    Mots-clés : lire fichier, ouvrir, contenu, code source, PDF, texte, fichier local

    Args:
        path:   chemin absolu du fichier
        offset: numéro de la première ligne à retourner (1-indexé, 0 = depuis le début)
        limit:  nombre de lignes à retourner (0 = tout le fichier)
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

    # ── PDF ───────────────────────────────────────────────────────────────────
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

    # ── Fichier texte avec plage de lignes ────────────────────────────────────
    if limit > 0 or offset > 0:
        # Lecture efficace ligne par ligne — pas de chargement complet en mémoire
        start = max(offset, 1)  # 1-indexé
        collected: list[str] = []
        total_lines = 0
        try:
            with p.open(encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    total_lines = lineno
                    if lineno < start:
                        continue
                    collected.append(line)
                    if limit > 0 and len(collected) >= limit:
                        break
            content = "".join(collected)
            return {
                "status": "ok", "name": p.name, "path": str(p),
                "ext": ext, "content": content,
                "lines_returned": len(collected),
                "offset": start,
                "size": f"{size // 1024}KB" if size >= 1024 else f"{size}B",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Fichier texte complet ─────────────────────────────────────────────────
    if size > _MAX_FILE_SIZE:
        return {
            "status": "too_large",
            "name": p.name,
            "size": f"{size // 1024}KB",
            "hint": f"Fichier trop grand ({size // 1024}KB > 200KB). Utilise offset= et limit= pour lire par plage.",
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


@tool("local_grep")
def local_grep(
    pattern: str,
    path: str = "",
    glob: str = "",
    output_mode: str = "content",
    context_lines: int = 0,
    case_insensitive: bool = False,
) -> Dict[str, Any]:
    """
    Cherche un pattern (regex) dans le contenu des fichiers d'un dossier ou projet.

    Utilise ce tool quand l'utilisateur veut :
    - trouver toutes les occurrences d'une fonction, variable, classe ou texte dans un projet
    - chercher du code dans des fichiers
    - localiser où une erreur est générée
    - trouver tous les imports d'un module

    Mots-clés : chercher dans fichiers, grep, pattern, occurrence, contenu, code, recherche texte,
    trouver où, classe, fonction, variable, import

    Args:
        pattern:          regex ou texte à chercher (ex: "def my_func", "import os", "TODO")
        path:             dossier ou fichier de départ (défaut : dossier projets)
        glob:             filtre de fichiers glob (ex: "*.py", "**/*.ts", "*.{js,ts}")
        output_mode:      "content" = lignes correspondantes (défaut)
                          "files"   = liste des fichiers contenant le pattern
                          "count"   = nombre d'occurrences par fichier
        context_lines:    nombre de lignes de contexte avant/après chaque match (défaut: 0)
        case_insensitive: True pour ignorer la casse (défaut: False)
    Returns:
        {"status": "ok", "pattern": "...", "matches": "...", "count": N}
    """
    base = path or str(get_projects_dir() or _HOME)
    search_path = Path(base)
    if not search_path.exists():
        return {"status": "error", "error": f"Chemin introuvable : {base}"}

    # ── Ripgrep (primary) ─────────────────────────────────────────────────────
    if _rg_available():
        cmd = ["rg", "--no-heading", "--max-filesize", "1M"]

        if output_mode == "files":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        else:
            cmd += ["-n"]                           # numéros de ligne
            if context_lines > 0:
                cmd += ["-C", str(context_lines)]

        if case_insensitive:
            cmd.append("-i")
        if glob:
            cmd += ["--glob", glob]

        # Ignore les dossiers inutiles
        cmd += ["--glob", "!.git", "--glob", "!node_modules",
                "--glob", "!.venv", "--glob", "!__pycache__"]

        cmd += [pattern, str(search_path)]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout
            # rg retourne 1 quand aucun match — ce n'est pas une erreur
            if result.returncode not in (0, 1):
                # Retombe sur grep
                pass
            else:
                truncated = len(output) > _MAX_GREP_OUTPUT
                output = output[:_MAX_GREP_OUTPUT]
                lines = [l for l in output.splitlines() if l]
                return {
                    "status": "ok" if lines else "no_match",
                    "pattern": pattern,
                    "path": str(search_path),
                    "output_mode": output_mode,
                    "matches": output,
                    "count": len(lines),
                    "truncated": truncated,
                }
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Timeout — affine le chemin ou le pattern"}
        except Exception as e:
            pass  # fallback to grep

    # ── Grep fallback ─────────────────────────────────────────────────────────
    cmd = ["grep", "-r"]
    if output_mode == "files":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")
    else:
        cmd.append("-n")
        if context_lines > 0:
            cmd += [f"-C{context_lines}"]
    if case_insensitive:
        cmd.append("-i")
    if glob:
        # grep --include supporte uniquement les patterns simples (pas **)
        simple_glob = glob.replace("**/", "")
        cmd += [f"--include={simple_glob}"]
    cmd += ["--exclude-dir=.git", "--exclude-dir=node_modules",
            "--exclude-dir=.venv", "--exclude-dir=__pycache__"]
    cmd += [pattern, str(search_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout
        if result.returncode not in (0, 1):
            return {"status": "error", "error": result.stderr}
        truncated = len(output) > _MAX_GREP_OUTPUT
        output = output[:_MAX_GREP_OUTPUT]
        lines = [l for l in output.splitlines() if l]
        return {
            "status": "ok" if lines else "no_match",
            "pattern": pattern,
            "path": str(search_path),
            "output_mode": output_mode,
            "matches": output,
            "count": len(lines),
            "truncated": truncated,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Timeout — affine le chemin ou le pattern"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("local_glob")
def local_glob(pattern: str, path: str = "") -> Dict[str, Any]:
    """
    Trouve des fichiers par pattern glob dans un dossier local, triés par date de modification.

    Utilise ce tool quand l'utilisateur veut :
    - lister tous les fichiers Python d'un projet
    - trouver tous les fichiers d'un type donné dans une arborescence
    - obtenir la liste des fichiers matchant un pattern précis

    Mots-clés : glob, pattern, tous les fichiers, type de fichier, extension, arborescence,
    **/*.py, *.ts, trouver par extension

    Différence avec local_find_file : celui-ci utilise un pattern exact (glob) plutôt
    qu'un nom approximatif.

    Args:
        pattern: pattern glob (ex: "**/*.py", "src/**/*.ts", "*.json", "tests/test_*.py")
        path:    dossier de base (défaut : dossier projets)
    Returns:
        {"status": "ok", "matches": [{"path", "name", "size", "modified"}, ...]}
    """
    base_str = path or str(get_projects_dir() or _HOME)
    base = Path(base_str)

    if not base.exists() or not base.is_dir():
        return {"status": "error", "error": f"Dossier introuvable : {base_str}"}

    try:
        raw_matches = list(base.glob(pattern))
    except Exception as e:
        return {"status": "error", "error": f"Pattern invalide : {e}"}

    # Garder uniquement les fichiers (pas les dossiers), trier par mtime décroissant
    files = [p for p in raw_matches if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    truncated = len(files) > _MAX_GLOB_RESULTS
    files = files[:_MAX_GLOB_RESULTS]

    results = []
    for p in files:
        try:
            stat = p.stat()
            size = stat.st_size
            import datetime
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            continue
        results.append({
            "path": str(p),
            "name": p.name,
            "ext": p.suffix.lower(),
            "size": f"{size // 1024}KB" if size >= 1024 else f"{size}B",
            "modified": mtime,
        })

    if not results:
        return {"status": "no_match", "pattern": pattern, "path": str(base), "matches": []}

    return {
        "status": "ok",
        "pattern": pattern,
        "path": str(base),
        "count": len(results),
        "truncated": truncated,
        "matches": results,
    }
