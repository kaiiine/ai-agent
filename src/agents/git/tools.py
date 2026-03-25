from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from langchain_core.tools import tool

_HOME = Path.home()


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
    """Trouve le repo git depuis un hint ou depuis $HOME."""
    if path_hint:
        p = Path(path_hint)
        if p.exists():
            return p
    # Cherche dans les dossiers projets courants
    for candidate in [Path.cwd(), _HOME / "Documents" / "projets-perso"]:
        code, _, _ = _git(["rev-parse", "--show-toplevel"], candidate)
        if code == 0:
            return candidate
    return None


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


@tool("url_fetch")
def url_fetch(url: str, max_chars: int = 20_000) -> Dict[str, Any]:
    """
    Récupère et retourne le contenu textuel d'une URL (page web, documentation, README).

    Utilise ce tool quand l'utilisateur veut :
    - lire le contenu d'une URL précise
    - accéder à de la documentation en ligne
    - récupérer un README GitHub ou une page de doc

    Mots-clés : URL, page web, lire lien, documentation, readme, github, accéder

    NE PAS utiliser pour les recherches générales — utiliser web_research_report pour ça.

    Args:
        url: URL à fetcher
        max_chars: nombre max de caractères retournés (défaut: 20000)
    Returns:
        {"status": "ok", "url": "...", "title": "...", "content": "..."}
    """
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Axon-Agent/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "")

        if "html" in content_type:
            try:
                from html.parser import HTMLParser

                class _TextExtractor(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.parts: list[str] = []
                        self._skip = False

                    def handle_starttag(self, tag, attrs):
                        if tag in {"script", "style", "nav", "footer", "header"}:
                            self._skip = True

                    def handle_endtag(self, tag):
                        if tag in {"script", "style", "nav", "footer", "header"}:
                            self._skip = False

                    def handle_data(self, data):
                        if not self._skip and data.strip():
                            self.parts.append(data.strip())

                parser = _TextExtractor()
                parser.feed(raw.decode("utf-8", errors="replace"))
                text = "\n".join(parser.parts)
            except Exception:
                text = raw.decode("utf-8", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")

        return {
            "status": "ok",
            "url": url,
            "content": text[:max_chars],
            "chars": len(text),
        }
    except Exception as e:
        return {"status": "error", "url": url, "error": str(e)}
