from __future__ import annotations
import shutil
import subprocess
import os
from pathlib import Path
from typing import Optional, Dict, Any
from langchain_core.tools import tool

_HOME = Path.home()
_cwd: Path = _HOME  # répertoire de travail courant de la session
_bg_procs: dict[str, subprocess.Popen] = {}  # label → processus background actif


def get_cwd() -> Path:
    return _cwd

# RTK — proxy CLI qui comprime les outputs pour économiser les tokens.
# Détecté une fois au chargement. Si absent → commandes brutes.
_RTK: str | None = shutil.which("rtk")


_SHELL_OPS = ("&&", "||", " | ", ";", "2>&", ">&", "$(", "`")


def _wrap_rtk(cmd: str) -> str:
    """Préfixe la commande avec rtk si disponible.

    RTK ne supporte pas les opérateurs shell (&&, |, redirections) — il essaie
    d'exec la commande directement sans passer par un shell. On saute le wrapping
    pour ces cas afin d'éviter les boucles infinies de exit 127.
    """
    if not _RTK:
        return cmd
    stripped = cmd.strip()
    if stripped.endswith("&"):
        return cmd  # background process — ne pas envelopper
    if any(op in stripped for op in _SHELL_OPS):
        return cmd  # commande composée — RTK ne sait pas gérer sans shell
    return f"{_RTK} {stripped}"  # chemin absolu pour éviter les problèmes de PATH

# Commandes qui modifient l'état système — nécessitent confirmation explicite de l'utilisateur
_DESTRUCTIVE_PREFIXES = (
    "rm ", "rmdir", "dd ", "mkfs", "sudo rm", "sudo dd",
    "git reset --hard", "git clean -f", "git push --force",
    "pip uninstall", "pacman -R", "yay -R",
)

# Écriture de fichiers — doit passer par propose_file_change dans le coding specialist
_WRITE_PATTERNS = ("sed -i", "cat >", "cat >>", "tee /", "echo > /", "echo >> /")


def _is_file_write(cmd: str) -> bool:
    c = cmd.strip()
    return any(p in c for p in _WRITE_PATTERNS)


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

    if _is_file_write(command):
        return {
            "status": "blocked",
            "command": command,
            "message": "Écriture de fichier via shell bloquée. Utilise propose_file_change(path, content, description) pour toute modification de fichier.",
        }

    work_dir = Path(cwd) if cwd else None
    if work_dir and not work_dir.exists():
        work_dir = None

    timeout = min(timeout, 300)
    work_dir = work_dir or _cwd
    env = {**os.environ, "TERM": "xterm-256color"}

    # Background process (command ends with &) — use Popen to track PID
    stripped_cmd = command.strip()
    if stripped_cmd.endswith("&"):
        bare = stripped_cmd[:-1].strip()
        label = bare.split()[0] if bare else bare
        try:
            proc = subprocess.Popen(
                bare,
                shell=True,
                cwd=str(work_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            _bg_procs[label] = proc
            return {
                "status": "ok",
                "stdout": f"Processus démarré en arrière-plan (PID {proc.pid})",
                "stderr": "",
                "exit_code": 0,
                "pid": proc.pid,
                "label": label,
                "cwd": str(work_dir),
                "note": f"Arrête-le avec shell_kill_bg(label='{label}') ou shell_kill_bg(port=<N>) après usage.",
            }
        except Exception as e:
            return {"status": "error", "stdout": "", "stderr": str(e), "exit_code": -1, "cwd": str(work_dir)}

    command = _wrap_rtk(command)
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        stderr = result.stderr[:5_000]
        # exit 127 = command not found — enrich stderr so the model can diagnose
        if result.returncode == 127 and not stderr.strip():
            cmd_token = command.strip().split()[0] if command.strip() else command
            stderr = (
                f"exit 127: commande introuvable — '{cmd_token}' n'est pas dans le PATH "
                f"ou le chemin est incorrect.\n"
                f"Essaie : which {cmd_token.split('/')[-1]}  ou utilise le nom court (pnpm, npm, npx…) "
                f"sans chemin absolu."
            )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "stdout": result.stdout[:10_000],
            "stderr": stderr,
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


@tool("shell_kill_bg")
def shell_kill_bg(label: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
    """
    Arrête un processus background lancé avec shell_run("... &").
    À appeler TOUJOURS après avoir utilisé un dev server pour vérification (pnpm run dev, npm run dev, etc.)
    afin de libérer le port pour l'utilisateur.

    Args:
        label: nom du processus tel que retourné par shell_run (ex: "pnpm", "node")
        port: numéro de port à libérer (ex: 3000, 8080) — tue tout process sur ce port
    Returns:
        {"status": "ok", "killed": [...]} ou {"status": "error"}
    """
    killed = []

    if label and label in _bg_procs:
        proc = _bg_procs.pop(label)
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        killed.append(f"{label} (PID {proc.pid})")

    if port:
        try:
            result = subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                killed.append(f"port {port}")
        except Exception:
            try:
                subprocess.run(
                    f"lsof -ti tcp:{port} | xargs kill -9",
                    shell=True, timeout=5, capture_output=True,
                )
                killed.append(f"port {port}")
            except Exception:
                pass

    if killed:
        return {"status": "ok", "killed": killed}
    return {"status": "error", "error": "Aucun processus trouvé pour ce label ou port."}


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
        # Invalidate the @-mention file cache so completions reflect the new project
        try:
            import src.ui.completer as _completer
            _completer._file_cache_ts = 0.0
        except Exception:
            pass
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
