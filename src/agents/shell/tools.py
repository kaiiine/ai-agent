from __future__ import annotations
import subprocess
import os
from pathlib import Path
from typing import Optional, Dict, Any
from langchain_core.tools import tool

_HOME = Path.home()
_cwd: Path = _HOME  # répertoire de travail courant de la session

# Commandes qui modifient l'état système — nécessitent confirmation explicite de l'utilisateur
_DESTRUCTIVE_PREFIXES = (
    "rm ", "rmdir", "dd ", "mkfs", "sudo rm", "sudo dd",
    "git reset --hard", "git clean -f", "git push --force",
    "pip uninstall", "pacman -R", "yay -R",
)


def _is_destructive(cmd: str) -> bool:
    c = cmd.strip().lower()
    return any(c.startswith(p) for p in _DESTRUCTIVE_PREFIXES)


@tool("shell_run")
def shell_run(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 30,
    confirmed: bool = False,
) -> Dict[str, Any]:
    """
    Exécute une commande shell et retourne stdout/stderr/exit_code.

    Utilise ce tool quand l'utilisateur veut :
    - lancer un script Python, Bash ou n'importe quelle commande terminal
    - compiler, tester ou builder un projet
    - exécuter une commande système
    - installer des paquets, démarrer un serveur, lancer des tests

    Mots-clés : terminal, commande, shell, bash, script, exécuter, lancer, installer, build, npm, pip, run

    RÈGLE DE SÉCURITÉ : Si la commande est destructive (rm, git reset --hard, etc.),
    demander TOUJOURS confirmation explicite à l'utilisateur avant d'appeler ce tool.
    Pour les commandes destructives, passer confirmed=True seulement après confirmation.

    Args:
        command: commande shell à exécuter
        cwd: répertoire de travail (défaut: home)
        timeout: timeout en secondes (défaut: 30, max: 300)
        confirmed: True si l'utilisateur a explicitement confirmé une commande destructive
    Returns:
        {"status": "ok"|"error"|"timeout", "stdout": "...", "stderr": "...", "exit_code": N, "cwd": "..."}
    """
    if _is_destructive(command) and not confirmed:
        return {
            "status": "requires_confirmation",
            "command": command,
            "message": "Commande destructive détectée. Demander confirmation explicite à l'utilisateur avant d'exécuter.",
        }

    work_dir = Path(cwd) if cwd else None
    if work_dir and not work_dir.exists():
        work_dir = None

    timeout = min(timeout, 300)
    work_dir = work_dir or _cwd

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "TERM": "xterm-256color"},
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "stdout": result.stdout[:10_000],
            "stderr": result.stderr[:5_000],
            "exit_code": result.returncode,
            "cwd": str(work_dir),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "stdout": "",
            "stderr": f"Timeout après {timeout}s",
            "exit_code": -1,
            "cwd": str(work_dir),
        }
    except Exception as e:
        return {"status": "error", "stdout": "", "stderr": str(e), "exit_code": -1, "cwd": str(work_dir)}


@tool("notify")
def notify(title: str, message: str, urgency: str = "normal") -> Dict[str, Any]:
    """
    Envoie une notification desktop via notify-send.

    Utilise ce tool quand l'utilisateur veut :
    - être notifié de la fin d'une tâche longue
    - envoyer une alerte ou un rappel sur le bureau
    - signaler un événement important visuellement

    Mots-clés : notification, alerte, bureau, desktop, notifier, rappel, popup

    Args:
        title: titre de la notification
        message: corps du message
        urgency: "low" | "normal" | "critical"
    Returns:
        {"status": "ok"} ou {"status": "error"}
    """
    urgency = urgency if urgency in {"low", "normal", "critical"} else "normal"
    try:
        subprocess.run(
            ["notify-send", "-u", urgency, title, message],
            timeout=5,
            check=True,
        )
        return {"status": "ok"}
    except FileNotFoundError:
        return {"status": "error", "error": "notify-send non disponible"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("clipboard_read")
def clipboard_read() -> Dict[str, Any]:
    """
    Lit le contenu actuel du presse-papiers.

    Utilise ce tool quand l'utilisateur veut :
    - accéder au texte qu'il a copié
    - récupérer une URL, du code ou du texte depuis le clipboard
    - utiliser ce qui est dans son presse-papiers

    Mots-clés : presse-papiers, clipboard, copier, coller, récupérer

    Returns:
        {"status": "ok", "content": "...", "type": "text"}
    """
    for cmd in [["wl-paste"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                return {"status": "ok", "content": result.stdout[:50_000], "type": "text"}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return {"status": "error", "error": "Aucun gestionnaire de clipboard disponible (wl-paste, xclip, xsel)"}


def _find_dir(name: str) -> Optional[Path]:
    """Cherche un dossier par nom approximatif depuis $HOME via fd ou find."""
    needle = name.lower()
    # 1. fd (rapide)
    for cmd in [
        ["fd", "--type", "d", "--max-depth", "6", name, str(_HOME)],
        ["find", str(_HOME), "-type", "d", "-iname", f"*{name}*",
         "-not", "-path", "*/.git/*", "-not", "-path", "*/node_modules/*",
         "-not", "-path", "*/__pycache__/*"],
    ]:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
            if not lines:
                continue
            # Trier par profondeur (moins profond = meilleur) puis par similarité
            def _score(p: str) -> tuple:
                parts = p.split("/")
                depth = len(parts)
                basename = parts[-1].lower()
                exact = basename == needle
                contains = needle in basename
                return (not exact, not contains, depth)
            lines.sort(key=_score)
            return Path(lines[0])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


@tool("shell_cd")
def shell_cd(path: str) -> Dict[str, Any]:
    """
    Change le répertoire de travail courant pour les prochaines commandes shell.

    Utilise ce tool quand l'utilisateur veut :
    - naviguer dans un dossier ou projet spécifique
    - aller dans un répertoire avant d'exécuter des commandes
    - se placer dans un projet pour lancer des scripts

    Mots-clés : changer dossier, naviguer, aller dans, cd, répertoire, projet

    Persiste pour tous les appels shell_run suivants.
    Supporte les chemins absolus, relatifs ET les noms approximatifs de projets.

    Args:
        path: chemin absolu, relatif, ou nom approximatif du dossier (ex: "rag-python", "ai-agent", "src")
    Returns:
        {"status": "ok", "cwd": "/nouveau/chemin"} ou {"status": "error"}
    """
    global _cwd

    # 1. Essai direct (absolu ou relatif au cwd)
    p = Path(path)
    if not p.is_absolute():
        p = (_cwd / path).resolve()
    if p.exists() and p.is_dir():
        _cwd = p
        return {"status": "ok", "cwd": str(_cwd)}

    # 2. Recherche fuzzy depuis $HOME
    found = _find_dir(path)
    if found and found.is_dir():
        _cwd = found.resolve()
        return {"status": "ok", "cwd": str(_cwd), "resolved_from": path}

    return {"status": "error", "error": f"Dossier introuvable : {path}"}


@tool("shell_pwd")
def shell_pwd() -> Dict[str, Any]:
    """
    Retourne le répertoire de travail courant de la session shell.

    Utilise ce tool quand l'utilisateur veut :
    - savoir dans quel dossier on se trouve actuellement
    - connaître le répertoire courant avant d'exécuter des commandes

    Mots-clés : répertoire courant, où suis-je, dossier actuel, cwd, pwd

    Returns:
        {"cwd": "/chemin/courant"}
    """
    return {"cwd": str(_cwd)}


@tool("shell_ls")
def shell_ls(path: Optional[str] = None, all_files: bool = False) -> Dict[str, Any]:
    """
    Liste rapidement le contenu du répertoire courant ou d'un sous-dossier.

    Utilise ce tool quand l'utilisateur veut :
    - voir les fichiers d'un projet en cours
    - lister les fichiers du dossier courant
    - explorer rapidement la structure d'un repo

    Mots-clés : lister, ls, fichiers, dossier courant, contenu répertoire, explorer projet

    Args:
        path: sous-dossier à lister (relatif au cwd ou absolu). None = cwd courant.
        all_files: True pour inclure les fichiers cachés (.gitignore, .env, etc.)
    Returns:
        {"status": "ok", "cwd": "...", "entries": [{"name", "type", "size"}, ...]}
    """
    target = Path(path) if path else _cwd
    if not target.is_absolute():
        target = (_cwd / target).resolve()
    if not target.exists():
        return {"status": "error", "error": f"Dossier introuvable : {target}"}
    if not target.is_dir():
        return {"status": "error", "error": f"Pas un dossier : {target}"}

    try:
        entries = []
        for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            if not all_files and entry.name.startswith("."):
                continue
            if entry.is_dir():
                entries.append({"name": entry.name + "/", "type": "dir"})
            else:
                size = entry.stat().st_size
                size_str = f"{size // 1024}KB" if size >= 1024 else f"{size}B"
                entries.append({"name": entry.name, "type": "file", "size": size_str, "ext": entry.suffix})
        return {"status": "ok", "cwd": str(target), "count": len(entries), "entries": entries}
    except PermissionError as e:
        return {"status": "error", "error": str(e)}


@tool("clipboard_write")
def clipboard_write(text: str) -> Dict[str, Any]:
    """
    Écrit du texte dans le presse-papiers pour pouvoir le coller ailleurs.

    Utilise ce tool quand l'utilisateur veut :
    - copier du texte dans le presse-papiers
    - préparer du code ou du texte à coller dans une autre appli
    - mettre un résultat dans le clipboard

    Mots-clés : copier, clipboard, presse-papiers, coller, mettre en mémoire

    Args:
        text: texte à copier
    Returns:
        {"status": "ok"} ou {"status": "error"}
    """
    for cmd in [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
        try:
            result = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                return {"status": "ok", "chars": len(text)}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return {"status": "error", "error": "Aucun gestionnaire de clipboard disponible"}
