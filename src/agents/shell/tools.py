from __future__ import annotations
import shutil
import subprocess
import os
import signal
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from langchain_core.tools import tool

from .ecriture import analyser_ecriture

_HOME = Path.home()
_cwd: Path = _HOME  # répertoire de travail courant de la session
_bg_procs: dict[str, subprocess.Popen] = {}  # label → processus background actif

_shell_stream_callback = None


def set_shell_stream_callback(fn) -> None:
    global _shell_stream_callback
    _shell_stream_callback = fn


def _emit_shell_stream(line: str) -> None:
    if _shell_stream_callback:
        try:
            _shell_stream_callback(line)
        except Exception:
            pass


def _compact_shell_output(text: str, max_chars: int = 10_000) -> str:
    import re

    text = re.sub(r"^\s*(✓\s*)?Download https?://.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)

    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) > 80:
        lines = lines[:40] + [f"...[{len(lines) - 80} lines omitted]..."] + lines[-40:]

    return "\n".join(lines)[:max_chars]


def get_cwd() -> Path:
    return _cwd


def set_cwd(path: str | Path) -> None:
    global _cwd
    p = Path(path).expanduser().resolve()
    if p.is_dir():
        _cwd = p

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

# Commandes qui modifient l'état système — nécessitent confirmation explicite.
#
# L'UNION des vocabulaires, jamais celui de l'OS détecté. Ces listes étaient
# purement POSIX, si bien que `Remove-Item -Recurse -Force C:\Users`,
# `del /f /s /q C:\`, `Format-Volume` et `diskpart` passaient SANS confirmation :
# le filet de sécurité disparaissait en silence en changeant de machine.
#
# Choisir la liste d'après l'OS détecté aurait rouvert la même faille par un
# autre chemin — une détection qui se trompe (conteneur, WSL, shell POSIX sous
# Windows) désarmerait le garde. Une union ne peut se tromper que dans le sens
# sûr : un `del /f /s` tapé sous Linux ne coûte qu'une confirmation de trop.
_DESTRUCTIVE_POSIX = (
    "rm ", "rmdir", "dd ", "mkfs", "sudo rm", "sudo dd", "shred ",
    "pip uninstall", "pacman -R", "yay -R", "apt remove", "apt purge",
    "apt-get remove", "apt-get purge", "dnf remove", "zypper remove",
    "apk del", "brew uninstall",
)
_DESTRUCTIVE_WINDOWS = (
    "remove-item", "ri ", "del ", "erase ", "rd ", "rmdir ", "format ",
    "format-volume", "clear-disk", "diskpart", "winget uninstall",
    "cipher /w", "takeown", "icacls",
)
_DESTRUCTIVE_VCS = (
    "git reset --hard", "git clean -f", "git push --force", "git push -f",
)
_DESTRUCTIVE_PREFIXES = _DESTRUCTIVE_POSIX + _DESTRUCTIVE_WINDOWS + _DESTRUCTIVE_VCS

# Écriture de fichiers — doit passer par propose_file_change dans le coding specialist
_WRITE_PATTERNS = (
    "sed -i", "cat >", "cat >>", "tee /", "echo > /", "echo >> /",
    "set-content", "out-file", "add-content",
)

# Cibles dont la suppression détruirait le système ou le dossier courant.
# POSIX et Windows ensemble, pour la même raison que ci-dessus.
_RM_CATASTROPHIC_TARGETS = (
    ".", "./", "..", "../", "/", "~", "~/", "*",
    "$home", "${home}", "$pwd", "${pwd}",
    "c:", "c:\\", "d:", "d:\\", "%userprofile%", "%homepath%", "%systemroot%",
    "$env:userprofile", "$env:homepath", "$env:systemroot", "$home\\",
    ".\\", "..\\", "*.*",
)

#: Verbes de suppression, tous OS confondus. `rm` seul laissait passer
#: `Remove-Item`, `del` et `rd`, qui font exactement la même chose ailleurs.
_VERBES_SUPPRESSION = r"(?:sudo\s+)?(?:rm|rmdir|remove-item|ri|del|erase|rd)"


#: Ce que « commande introuvable » vaut selon le shell : 127 pour les POSIX,
#: 9009 pour cmd.exe, et un simple 1 pour PowerShell — qui ne le dit que dans
#: son texte. Reconnaître les trois est la condition pour que la re-détection
#: parte quel que soit l'OS.
_CODES_INTROUVABLE = (127, 9009)
_TEXTES_INTROUVABLE = (
    "command not found", "not found", "not recognized",
    "no such file or directory", "commandnotfoundexception",
    "n'est pas reconnu",
)


def _commande_introuvable(exit_code: int, sortie: str) -> bool:
    """Vrai quand l'échec est « ce binaire n'existe pas », pas « il a échoué ».

    La condition testait aussi que la sortie soit VIDE. Avec `rtk` installé,
    elle ne l'est jamais — il écrit son propre message — si bien que toute cette
    branche était morte sur la machine où elle comptait le plus.
    """
    if exit_code in _CODES_INTROUVABLE:
        return True
    bas = (sortie or "").lower()
    return exit_code != 0 and any(t in bas for t in _TEXTES_INTROUVABLE)


def _is_catastrophic_rm(cmd: str) -> bool:
    """Suppression visant une cible qui détruirait le système ou le dossier courant.

    Reconnaît les verbes des trois familles : `rm`/`rmdir` (POSIX),
    `Remove-Item`/`ri` (PowerShell), `del`/`erase`/`rd` (cmd).
    """
    import re
    c = cmd.strip()
    # Normalise : <verbe> [-options | /options] <cible>
    m = re.match(rf"^{_VERBES_SUPPRESSION}\s+((?:[-/][a-zA-Z:]+\s+)*)(.+)$", c, re.I)
    if not m:
        return False
    cible = m.group(2).strip().strip('"\'').lower()
    # Un chemin PowerShell peut porter un préfixe de fournisseur.
    cible = cible.removeprefix("filesystem::")
    cible = cible.rstrip("/").rstrip("\\")
    # Rend "" pour « rm -rf / » une fois la barre retirée.
    nu = cible if cible else "/"
    return nu in {t.rstrip("/").rstrip("\\") or "/" for t in _RM_CATASTROPHIC_TARGETS}


def _is_file_write(cmd: str) -> bool:
    c = cmd.strip()
    return any(p in c for p in _WRITE_PATTERNS)


def _is_destructive(cmd: str) -> bool:
    """La commande exige-t-elle une confirmation explicite ?

    Les préfixes sont normalisés en minuscules à la comparaison. Sans cela
    `pacman -R` et `yay -R`, écrits avec un R majuscule dans la liste, ne
    déclenchaient JAMAIS de confirmation : la commande était abaissée, le
    préfixe non. Deux désinstallations de paquets passaient donc librement.
    """
    c = cmd.strip().lower()
    return any(c.startswith(p.lower()) for p in _DESTRUCTIVE_PREFIXES)


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
    if _is_catastrophic_rm(command):
        return {
            "status": "blocked",
            "command": command,
            "message": "Commande bloquée : rm sur le dossier courant (.), racine (/), home (~) ou wildcard (*) est interdit, même avec confirmation.",
        }

    if _is_destructive(command) and not confirmed:
        return {
            "status": "requires_confirmation",
            "command": command,
            "message": "Commande destructive détectée. Demander confirmation explicite à l'utilisateur avant d'exécuter.",
        }

    ecriture = analyser_ecriture(command)
    if ecriture is not None:
        if not ecriture.distante:
            # LOCAL — inchangé. `edit_file` fait mieux : il n'envoie que le
            # fragment modifié, et l'utilisateur relit un diff avant écriture.
            return {
                "status": "blocked",
                "command": command,
                "target": ecriture.cible,
                "message": "Écriture de fichier via shell bloquée. Utilise edit_file(path, old_string, new_string) pour modifier une partie d'un fichier existant, propose_file_change(path, content, description) pour en créer un.",
            }
        if not confirmed:
            # DISTANT — aucun équivalent : `edit_file` ne prend qu'un chemin
            # local. Refuser ici enfermait l'agent, qui n'avait plus qu'à rendre
            # un mode d'emploi à l'utilisateur.
            #
            # On confirme donc, mais pas « à la manière de rm -rf » : approuver
            # une commande sans voir ce qu'elle écrit, c'est approuver un effet
            # qu'on ne connaît pas. L'aperçu montre le fichier, le mode, et le
            # CONTENU quand il se lit dans la commande.
            return {
                "status": "requires_confirmation",
                "command": command,
                "host": ecriture.hote,
                "target": ecriture.cible,
                "append": ecriture.ajoute,
                "preview": ecriture.apercu(),
                "message": (
                    "Écriture sur une machine DISTANTE. Montre l'aperçu ci-dessous "
                    "à l'utilisateur TEL QUEL et attends son accord explicite, puis "
                    "rappelle shell_run avec confirmed=True. Ne résume pas le "
                    "contenu : il doit voir ce qui sera écrit."),
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

    cmd_lower = command.lower()

    if any(x in cmd_lower for x in ("deno check", "deno test", "deno task", "deno cache")):
        timeout = max(timeout, 180)

    if any(x in cmd_lower for x in ("npm install", "pnpm install", "yarn install", "npm audit", "pnpm audit")):
        timeout = max(timeout, 180)

    timeout = min(timeout, 300)
    command = _wrap_rtk(command)

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            # Session dédiée : la commande et TOUS ses descendants forment un
            # groupe qu'on peut tuer d'un bloc. Sans elle, tuer `proc` ne tue que
            # l'enveloppe — `rtk sleep 10` laisse un `sleep` orphelin qui garde le
            # tube ouvert, et la lecture bloque jusqu'au bout malgré l'échéance.
            start_new_session=True,
        )

        output_lines: list[str] = []

        # Le délai est armé AVANT la lecture, pas après.
        #
        # `for line in proc.stdout` bloque jusqu'à la fermeture du flux, donc
        # jusqu'à la fin du processus : le `proc.wait(timeout=...)` qui suivait
        # n'était atteint qu'une fois la commande terminée, et n'expirait jamais.
        # Un `sleep 10` avec `timeout=1` tournait dix secondes et rendait « ok » ;
        # une commande qui ne rend pas la main aurait figé l'agent indéfiniment.
        #
        # Une minuterie tue le processus à l'échéance : le flux se ferme, la
        # boucle rend la main, et la sortie déjà reçue est conservée — ce qu'un
        # `wait(timeout=...)` seul ne permet pas.
        expire = threading.Event()

        def _echeance() -> None:
            expire.set()
            try:
                # Le GROUPE, pas seulement le processus lancé : l'enveloppe rtk
                # et le shell intermédiaire ont des enfants qui survivraient.
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        minuterie = threading.Timer(timeout, _echeance)
        minuterie.daemon = True
        minuterie.start()

        try:
            stdout = proc.stdout
            if stdout:
                for line in stdout:
                    clean = line.rstrip("\n")
                    output_lines.append(clean)
                    _emit_shell_stream(clean)
            exit_code = proc.wait()
        finally:
            minuterie.cancel()

        if expire.is_set():
            stdout_text = _compact_shell_output("\n".join(output_lines))
            return {
                "status": "timeout",
                "stdout": stdout_text,
                "stderr": f"Timeout après {timeout}s",
                "exit_code": -1,
                "cwd": str(work_dir),
            }

        stdout_text = _compact_shell_output("\n".join(output_lines))
        stderr = ""

        if _commande_introuvable(exit_code, stdout_text):
            cmd_token = command.strip().split()[0] if command.strip() else command
            # « Commande introuvable » est le symptôme d'un contexte machine
            # périmé : on croyait pacman, on est dans un conteneur Debian. Le
            # cache est vidé ici pour que le PROCHAIN prompt reparte d'une
            # détection fraîche — sans quoi la consigne « re-détecter » du skill
            # reste un vœu que rien n'exauce.
            try:
                from src.infra.systeme import oublier
                oublier()
            except Exception:
                pass
            stderr = (
                f"exit 127: commande introuvable — '{cmd_token}' n'est pas dans le PATH "
                f"ou le chemin est incorrect.\n"
                f"Le contexte MACHINE a été re-détecté : relis-le avant de retenter, "
                f"il peut désigner un autre gestionnaire de paquets.\n"
                f"Essaie : command -v {cmd_token.split('/')[-1]}  ou utilise le nom court "
                f"(pnpm, npm, npx…) sans chemin absolu."
            )

        return {
            "status": "ok" if exit_code == 0 else "error",
            "stdout": stdout_text,
            "stderr": stderr[:5_000],
            "exit_code": exit_code,
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
            # Prefer: exact name > inside project roots > shallower depth
            from src.utils.paths import get_projects_dir as _gpd
            _projects = str(_gpd())
            def _score(p: str) -> tuple:
                parts = p.split("/")
                depth = len(parts)
                basename = parts[-1].lower()
                exact = basename == needle
                contains = needle in basename
                in_projects = p.startswith(_projects)
                return (not exact, not contains, not in_projects, depth)
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
