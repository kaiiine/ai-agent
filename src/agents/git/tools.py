from __future__ import annotations

import subprocess
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Dict, Any, List

from langchain_core.tools import tool

_HOME = Path.home()


# ── Git helpers ───────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path, timeout: int = 15) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def _find_repo(path_hint: Optional[str]) -> Optional[Path]:
    """Trouve le repo git depuis un hint ou depuis le cwd courant."""
    if path_hint:
        p = Path(path_hint)
        if p.exists():
            return p
    from src.utils.paths import get_projects_dir
    for candidate in [Path.cwd(), get_projects_dir()]:
        code, _, _ = _git(["rev-parse", "--show-toplevel"], candidate)
        if code == 0:
            return candidate
    return None


# ── URL fetch cache (LRU, 15 min TTL) ────────────────────────────────────────

_FETCH_CACHE: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_CACHE_TTL = 900    # secondes
_CACHE_MAX = 50


def _cache_get(url: str) -> dict | None:
    if url not in _FETCH_CACHE:
        return None
    ts, data = _FETCH_CACHE[url]
    if time.time() - ts > _CACHE_TTL:
        del _FETCH_CACHE[url]
        return None
    _FETCH_CACHE.move_to_end(url)
    return data


def _cache_set(url: str, data: dict) -> None:
    _FETCH_CACHE[url] = (time.time(), data)
    _FETCH_CACHE.move_to_end(url)
    while len(_FETCH_CACHE) > _CACHE_MAX:
        _FETCH_CACHE.popitem(last=False)


def _html_to_markdown(html_bytes: bytes) -> str:
    """Convertit du HTML en Markdown. Utilise html2text si dispo, sinon HTMLParser."""
    html_str = html_bytes.decode("utf-8", errors="replace")
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links       = False
        h.ignore_images      = True
        h.ignore_tables      = False
        h.body_width         = 0       # pas de retour à la ligne forcé
        h.protect_links      = True
        h.wrap_links         = False
        return h.handle(html_str)
    except ImportError:
        pass

    # Fallback : HTMLParser stdlib — conserve la structure minimale
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        _SKIP_TAGS  = {"script", "style", "nav", "footer", "header", "noscript"}
        _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []
            self._skip_depth: int = 0

        def handle_starttag(self, tag: str, attrs) -> None:
            if tag in self._SKIP_TAGS:
                self._skip_depth += 1
            elif tag in self._BLOCK_TAGS and self.parts and self.parts[-1] != "\n":
                self.parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in self._SKIP_TAGS:
                self._skip_depth = max(0, self._skip_depth - 1)

        def handle_data(self, data: str) -> None:
            if self._skip_depth == 0 and data.strip():
                self.parts.append(data.strip())

    extractor = _TextExtractor()
    extractor.feed(html_str)
    return "\n".join(extractor.parts)


# ── Read-only git tools ───────────────────────────────────────────────────────

@tool("git_status")
def git_status(repo_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Affiche le statut Git du repo (fichiers modifiés, staged, non suivis).

    Utilise ce tool quand l'utilisateur veut :
    - voir l'état courant d'un repo Git
    - savoir quels fichiers ont été modifiés depuis le dernier commit
    - vérifier ce qui est staged ou non

    Mots-clés : git, statut, modifié, staged, commit, fichiers changés, status

    Args:
        repo_path: chemin vers le repo (optionnel, détecté automatiquement)
    """
    cwd = _find_repo(repo_path) or Path.cwd()
    try:
        code, out, err = _git(["status", "--short", "--branch"], cwd)
        if code != 0:
            return {"status": "error", "error": err or "Pas un repo git"}
        _, toplevel, _ = _git(["rev-parse", "--show-toplevel"], cwd)
        return {"status": "ok", "repo": toplevel.strip(), "output": out}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("git_log")
def git_log(repo_path: Optional[str] = None, n: int = 10) -> Dict[str, Any]:
    """
    Affiche l'historique des derniers commits d'un repo Git.

    Utilise ce tool quand l'utilisateur veut :
    - voir les derniers commits d'un projet
    - consulter l'historique Git
    - savoir qui a fait quoi et quand

    Mots-clés : git, historique, commits, log, journal, versions, branches

    Args:
        repo_path: chemin vers le repo (optionnel)
        n: nombre de commits à afficher (défaut: 10)
    """
    cwd = _find_repo(repo_path) or Path.cwd()
    try:
        code, out, err = _git(
            ["log", f"-{min(n, 50)}", "--oneline", "--decorate", "--graph"],
            cwd,
        )
        if code != 0:
            return {"status": "error", "error": err}
        return {"status": "ok", "log": out}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("git_diff")
def git_diff(repo_path: Optional[str] = None, staged: bool = False) -> Dict[str, Any]:
    """
    Affiche les différences (diff) des changements en cours par rapport au dernier commit.

    Utilise ce tool quand l'utilisateur veut :
    - voir ce qui a changé dans les fichiers modifiés
    - analyser les modifications avant un commit
    - comparer le code actuel avec la version commitée

    Mots-clés : git, diff, changements, modifications, avant commit, code modifié

    Args:
        repo_path: chemin vers le repo (optionnel)
        staged: True = diff des fichiers staged (à committer), False = unstaged
    """
    cwd = _find_repo(repo_path) or Path.cwd()
    try:
        args = ["diff", "--stat"] + (["--cached"] if staged else [])
        code, stat, _ = _git(args, cwd)

        args_full = ["diff"] + (["--cached"] if staged else [])
        _, full, _ = _git(args_full, cwd)

        if code != 0:
            return {"status": "error", "error": stat}
        return {
            "status": "ok",
            "staged": staged,
            "stat": stat,
            "diff": full[:15_000],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("git_suggest_commit")
def git_suggest_commit(repo_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyse les changements stagés et propose un message de commit formaté.

    Utilise ce tool quand l'utilisateur veut :
    - générer un message de commit pour ses modifications
    - avoir une suggestion de commit après git add
    - rédiger un commit clair et descriptif

    Mots-clés : git, commit, message, suggestion, staged, résumé changements

    Args:
        repo_path: chemin vers le repo (optionnel)
    Returns:
        {"status": "ok", "diff_summary": "...", "suggestion": "..."}
        Le champ suggestion contient un message de commit proposé — à valider par l'utilisateur.
    """
    cwd = _find_repo(repo_path) or Path.cwd()
    try:
        _, stat, _ = _git(["diff", "--cached", "--stat"], cwd)
        _, diff, _ = _git(["diff", "--cached"], cwd)

        if not stat.strip():
            return {"status": "empty", "message": "Aucun fichier staged. Lance git add d'abord."}

        return {
            "status": "ok",
            "diff_summary": stat,
            "diff": diff[:8_000],
            "instruction": (
                "Analyse ce diff et propose un message de commit en une ligne, "
                "format: 'type: description courte' (feat/fix/refactor/docs/chore). "
                "Ne pas committer — juste proposer le message pour validation."
            ),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Write git tools ───────────────────────────────────────────────────────────

@tool("git_add")
def git_add(
    paths: List[str],
    repo_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stage des fichiers pour le prochain commit (git add).

    Utilise ce tool quand l'utilisateur veut :
    - ajouter des fichiers modifiés au staging area
    - préparer un commit
    - stager tous les changements avant de committer

    Mots-clés : git add, stage, ajouter, préparer commit, staging

    RÈGLE : toujours montrer git_status avant, et demander confirmation si paths = ["."]

    Args:
        paths:     liste de chemins à stager (ex: ["src/main.py", "README.md"] ou ["."] pour tout)
        repo_path: chemin vers le repo (optionnel, détecté automatiquement)
    Returns:
        {"status": "ok", "staged": [...], "output": "..."}
    """
    cwd = _find_repo(repo_path) or Path.cwd()
    try:
        code, out, err = _git(["add", "--"] + paths, cwd)
        if code != 0:
            return {"status": "error", "error": err or out}
        # Vérifier ce qui est staged
        _, stat, _ = _git(["diff", "--cached", "--stat"], cwd)
        return {"status": "ok", "paths": paths, "staged_summary": stat.strip()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("git_commit")
def git_commit(
    message: str,
    repo_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Effectue un commit Git avec le message donné.

    Utilise ce tool quand l'utilisateur veut :
    - committer ses changements staged
    - enregistrer une version du code
    - créer un commit après git add

    Mots-clés : git commit, enregistrer, valider, sauvegarder version, commit

    RÈGLE ABSOLUE : afficher le diff (git_diff staged=True) à l'utilisateur et
    attendre sa confirmation avant d'appeler ce tool.

    Args:
        message:   message de commit (format recommandé: "type: description")
        repo_path: chemin vers le repo (optionnel)
    Returns:
        {"status": "ok", "commit": "hash...", "message": "..."}
    """
    cwd = _find_repo(repo_path) or Path.cwd()
    if not message.strip():
        return {"status": "error", "error": "Message de commit vide"}
    try:
        code, out, err = _git(["commit", "-m", message.strip()], cwd)
        if code != 0:
            return {"status": "error", "error": err or out}
        # Récupérer le hash du commit créé
        _, hash_out, _ = _git(["rev-parse", "--short", "HEAD"], cwd)
        return {
            "status": "ok",
            "commit": hash_out.strip(),
            "message": message.strip(),
            "output": out.strip(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("git_checkout")
def git_checkout(
    branch: str,
    create: bool = False,
    repo_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Crée ou bascule sur une branche Git.

    Utilise ce tool quand l'utilisateur veut :
    - créer une nouvelle branche de travail
    - basculer sur une branche existante
    - démarrer un développement isolé sur une branche

    Mots-clés : git branch, checkout, nouvelle branche, changer de branche, créer branche

    Args:
        branch:    nom de la branche (ex: "feat/my-feature", "main", "develop")
        create:    True pour créer la branche (-b), False pour juste basculer
        repo_path: chemin vers le repo (optionnel)
    Returns:
        {"status": "ok", "branch": "...", "created": True/False}
    """
    cwd = _find_repo(repo_path) or Path.cwd()
    if not branch.strip():
        return {"status": "error", "error": "Nom de branche vide"}
    try:
        args = ["checkout", "-b", branch] if create else ["checkout", branch]
        code, out, err = _git(args, cwd)
        if code != 0:
            return {"status": "error", "error": err or out}
        return {
            "status": "ok",
            "branch": branch,
            "created": create,
            "output": (out or err).strip(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("git_stash")
def git_stash(
    action: str = "push",
    message: str = "",
    repo_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Gère le stash Git (mise de côté temporaire de changements non commités).

    Utilise ce tool quand l'utilisateur veut :
    - mettre de côté des changements en cours pour travailler sur autre chose
    - récupérer des changements mis en stash
    - voir la liste des stashs existants

    Mots-clés : git stash, mettre de côté, sauvegarder temporaire, pop stash, liste stash

    Args:
        action:    "push"  = mettre les changements en stash (défaut)
                   "pop"   = récupérer le dernier stash
                   "list"  = afficher la liste des stashs
        message:   message descriptif pour le stash (uniquement pour action="push")
        repo_path: chemin vers le repo (optionnel)
    Returns:
        {"status": "ok", "action": "...", "output": "..."}
    """
    cwd = _find_repo(repo_path) or Path.cwd()
    action = action.lower().strip()
    if action not in ("push", "pop", "list"):
        return {"status": "error", "error": f"Action invalide '{action}' — utiliser push, pop ou list"}

    try:
        if action == "push":
            args = ["stash", "push"]
            if message.strip():
                args += ["-m", message.strip()]
        elif action == "pop":
            args = ["stash", "pop"]
        else:
            args = ["stash", "list"]

        code, out, err = _git(args, cwd)
        if code != 0:
            return {"status": "error", "error": err or out}
        return {"status": "ok", "action": action, "output": (out or err).strip()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── URL fetch ─────────────────────────────────────────────────────────────────

@tool("url_fetch")
def url_fetch(url: str, max_chars: int = 50_000) -> Dict[str, Any]:
    """
    Récupère et retourne le contenu d'une URL en Markdown (page web, documentation, README).

    Utilise ce tool quand l'utilisateur veut :
    - lire le contenu d'une URL précise
    - accéder à de la documentation en ligne
    - récupérer un README GitHub ou une page de doc

    Mots-clés : URL, page web, lire lien, documentation, readme, github, accéder

    NE PAS utiliser pour les recherches générales — utiliser web_research_report pour ça.
    Le résultat est mis en cache 15 minutes.

    Args:
        url:       URL à fetcher (http/https)
        max_chars: nombre max de caractères retournés (défaut: 50000)
    Returns:
        {"status": "ok", "url": "...", "content": "...", "cached": bool}
    """
    # ── Cache ─────────────────────────────────────────────────────────────────
    cached = _cache_get(url)
    if cached:
        return {**cached, "cached": True}

    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Axon-Agent/1.0)",
                "Accept": "text/markdown, text/html, */*",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw          = resp.read(10 * 1024 * 1024)   # max 10 MB
            content_type = resp.headers.get("Content-Type", "")

        # ── Conversion selon le type MIME ─────────────────────────────────────
        if "html" in content_type:
            content = _html_to_markdown(raw)
        else:
            content = raw.decode("utf-8", errors="replace")

        # Tronquer proprement sur une coupure de ligne
        if len(content) > max_chars:
            cut = content.rfind("\n", 0, max_chars)
            content = content[:cut if cut > 0 else max_chars]
            content += "\n\n…[contenu tronqué]"

        result = {
            "status": "ok",
            "url": url,
            "content": content,
            "chars": len(content),
            "cached": False,
        }
        _cache_set(url, result)
        return result

    except Exception as e:
        return {"status": "error", "url": url, "error": str(e)}
