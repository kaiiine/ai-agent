from __future__ import annotations
import shutil
import subprocess
import os
import signal
import threading
from pathlib import Path
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any
from langchain_core.tools import tool

from src.agents.coding.pending import FileChange, pending_changes
from .autorisation import est_autorisee
from .chemins_absolus import absolutiser
from .classification import (
    est_catastrophique,
    est_connue_sure,
    est_destructive,
)
from .ecriture import analyser_ecriture

_HOME = Path.home()


def _racine_des_projets() -> Path | None:
    try:
        from src.utils.paths import get_projects_dir

        racine = get_projects_dir()
        return racine if racine.is_dir() else None
    except Exception:                                        # noqa: BLE001
        return None


def _repertoire_de_lancement() -> Path:
    """Là où AXON a été lancé — comme n'importe quel outil de terminal.

    C'était `$HOME`, en dur. « Ce projet » n'avait donc aucun référent : le
    modèle partait le chercher, et sur cette machine `shell_cd projets-perso`
    depuis `$HOME` tombe dans un homonyme qui contient d'autres projets. On a vu
    l'agent finir dans `auratis-studio` pour une question sur `ai-agent`.

    Lancer depuis un projet, c'est déjà dire lequel : on ne devine plus.
    """
    try:
        depart = Path.cwd()
    except OSError:
        return _HOME
    return depart if depart != Path("/") else _HOME


_cwd: Path = _repertoire_de_lancement()  # répertoire de travail de la session
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


class ArgsShell(BaseModel):
    """Le schéma de `shell_run`, tolérant sur le nom du premier argument.

    Les modèles écrivent `cmd` au moins aussi souvent que `command` — c'est le
    nom qu'emploient la plupart des API shell. L'appel échouait alors sur une
    erreur de validation, le modèle réessayait avec l'autre nom, et ça marchait :
    deux appels pour un, à chaque commande, plus une ligne rouge à l'écran.
    Relevé trois fois sur un seul « supprime tout ce que contient ce dossier ».

    Le schéma annoncé garde `command` — c'est lui qu'on enseigne ; l'alias ne
    fait que rattraper. Durcir sans lui transformerait une frappe en échec.
    """

    model_config = ConfigDict(populate_by_name=True)

    command: str = Field(
        validation_alias=AliasChoices("command", "cmd"),
        serialization_alias="command",
        description="La commande shell à exécuter.",
    )
    cwd: Optional[str] = Field(
        default=None, description="Répertoire d'exécution. Par défaut, le cwd courant.")
    timeout: int = Field(default=30, description="Délai en secondes, 300 au plus.")


@tool("shell_run", args_schema=ArgsShell)
def shell_run(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Exécute une commande shell et retourne stdout/stderr/exit_code.

    Utilise ce tool quand l'utilisateur veut :
    - lancer un script Python, Bash ou n'importe quelle commande terminal
    - compiler, tester ou builder un projet
    - exécuter une commande système
    - installer des paquets, démarrer un serveur, lancer des tests

    Mots-clés : terminal, commande, shell, bash, script, exécuter, lancer, installer, build, npm, pip, run

    SÉCURITÉ : la confirmation ne dépend PAS de toi. Une commande destructive ou
    inhabituelle rend `requires_confirmation` ; l'accord est demandé à l'utilisateur
    par AXON lui-même, et tu n'as aucun moyen de t'en passer. N'annonce donc pas
    qu'une commande est faite tant que tu n'as pas vu son résultat.

    Args:
        command: commande shell à exécuter
        cwd: répertoire de travail (défaut: home)
        timeout: timeout en secondes (défaut: 300 max)
    Returns:
        {"status": "ok"|"error"|"timeout", "stdout": "...", "stderr": "...", "exit_code": N, "cwd": "..."}
    """
    # L'autorisation est à USAGE UNIQUE. La consulter à deux endroits du même
    # appel consommait le « oui » au premier garde et le faisait manquer au
    # second. Mesuré sur `ssh vps "monbinaire > /etc/motd"` : la branche
    # d'écriture consommait l'accord, la porte générale ne trouvait plus rien et
    # refusait — l'utilisateur répondait « oui », rien ne partait, le modèle
    # redemandait. Une boucle de questions, née d'un correctif de sécurité.
    _accord: list[bool] = []

    def autorisee() -> bool:
        if not _accord:
            _accord.append(est_autorisee(command))
        return _accord[0]

    if est_catastrophique(command):
        return {
            "status": "blocked",
            "command": command,
            "message": "Commande bloquée : rm sur le dossier courant (.), racine (/), home (~) ou wildcard (*) est interdit, même avec confirmation.",
        }

    ecriture = analyser_ecriture(command)
    if ecriture is not None and ecriture.composee:
        # Une validation ne doit couvrir qu'UN seul acte. Mesuré :
        # `echo x > /etc/motd && systemctl restart nginx` se lit « écrit
        # /etc/motd » — approuver ce diff redémarrerait nginx, effet que la
        # revue ne montrait pas. Et `rm -rf /tmp/cache | tee log.txt` n'a
        # aucun opérateur de chaînage : le tube seul cache déjà le `rm`.
        #
        # Découper vraiment la commande demanderait un parseur shell. Un
        # parseur approximatif sur des commandes qui effacent des données
        # est la faute qu'on refuse de commettre : ici l'enjeu n'est plus la
        # détection mais l'EXÉCUTION. On rend donc la main.
        return {
            "status": "blocked",
            "command": command,
            "target": ecriture.cible,
            "operator": ecriture.composee,
            "message": (
                f"Commande composée (opérateur « {ecriture.composee} ») contenant une "
                f"écriture vers {ecriture.cible}. Une confirmation ne peut porter que sur "
                "un seul acte : approuver l'écriture ferait aussi passer ce qui est "
                "enchaîné. Découpe en appels shell_run séparés, un par acte."),
        }


    if ecriture is not None:
        if not ecriture.distante and ecriture.contenu is not None:
            # LOCAL, contenu lisible — la revue DEVIENT l'action. On construit
            # le vrai diff et on le pousse dans la même file que `edit_file` ;
            # la commande shell n'est jamais exécutée, donc aucun effet de bord
            # ne peut se glisser derrière l'accord.
            cible = Path(ecriture.cible)
            if not cible.is_absolute():
                cible = (Path(cwd) if cwd else _cwd) / cible
            original = ""
            if cible.exists() and cible.is_file():
                try:
                    original = cible.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
            propose = (original + ecriture.contenu) if ecriture.ajoute else ecriture.contenu
            pending_changes.add(FileChange(
                path=str(cible),
                original=original,
                proposed=propose,
                description=f"shell : {ecriture.mode} de {cible.name}",
            ))
            return {
                "status": "proposed",
                "path": str(cible),
                "awaiting_confirmation": True,
                "message": (
                    f"Écriture convertie en proposition relue ({ecriture.mode}). "
                    "L'utilisateur verra le diff et tranchera ; la commande shell "
                    "elle-même ne sera PAS exécutée. N'appelle pas shell_run à nouveau "
                    "pour ce fichier."),
            }

        #: Les outils qui CAPTURENT une sortie. Eux seuls justifient une
        #: confirmation quand le contenu est illisible : il n'existe pas encore.
        #: `sed -i`, `dd`, `truncate` modifient au contraire un fichier DÉJÀ là,
        #: ce que `edit_file` fait mieux — avec un diff. Ouvrir le cas 2 à tout
        #: contenu illisible aurait relâché le garde là où l'issue existait.
        capture = ecriture.outil in ("redirection", "tee")

        if not ecriture.distante and not capture:
            return {
                "status": "blocked",
                "command": command,
                "target": ecriture.cible,
                "message": (
                    f"Modification sur place ({ecriture.outil}) d'un fichier local. Utilise "
                    "edit_file(path, old_string, new_string) pour changer une partie d'un "
                    "fichier existant, propose_file_change(path, content, description) pour "
                    "le réécrire entièrement : l'utilisateur y relit un diff."),
            }

        if not autorisee():
            if not ecriture.distante:
                # LOCAL, contenu NON lisible — le cas qu'aucune autre porte ne
                # sert. `mycommand > sortie.log` ne peut pas passer par
                # `propose_file_change` : il faudrait lancer la commande d'abord,
                # et `_compact_shell_output` tronque à 80 lignes / 10 000
                # caractères. Le fichier serait amputé en silence.
                #
                # On ne peut pas montrer de diff : le contenu n'existe pas encore.
                # On montre donc ce qu'on a — la commande, la cible, le mode — et
                # on le dit franchement.
                return {
                    "status": "requires_confirmation",
                    "command": command,
                    "target": ecriture.cible,
                    "append": ecriture.ajoute,
                    "preview": ecriture.apercu(),
                    "message": (
                        "Écriture dont le contenu ne se lit pas dans la commande. Montre "
                        "l'aperçu ci-dessous à l'utilisateur TEL QUEL. AXON lui demandera "
                        "son accord — tu n'as pas à le recueillir toi-même, ni à rappeler "
                        "shell_run. Si le contenu, lui, est connu de toi, passe plutôt par "
                        "propose_file_change : il donne un diff."),
                }
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
                    "à l'utilisateur TEL QUEL. AXON lui demandera son accord. Ne "
                    "résume pas le contenu : il doit voir ce qui sera écrit."),
            }

    # La porte unique. Deux raisons de la franchir, une seule façon : une
    # autorisation venue d'ailleurs que du modèle.
    #
    # Le DÉFAUT est inversé : ce qui n'est pas reconnu sûr demande un accord, au
    # lieu de s'exécuter. La liste des enveloppes retirées par la détection est
    # finie par nature (`python -c`, un alias, une fonction shell lui échappent) ;
    # inverser le défaut fait qu'un oubli devient une question posée, et non une
    # exécution silencieuse.
    # Ce qu'on approuve doit être ce qui s'exécute. « rm -rf ./* » ne dit pas ce
    # que `./` désigne — même écran pour un dossier d'essai et pour la racine
    # d'un projet — et le répertoire courant peut encore changer entre la
    # question et la réponse. On résout AVANT, donc la commande montrée est
    # littéralement celle qui partira. Ce qui reste relatif (commande enchaînée,
    # argument qui n'est pas un chemin) n'est pas réécrit, et la confirmation
    # montre alors le répertoire à côté.
    base = Path(cwd) if cwd else _cwd
    command = absolutiser(command, base)

    if not est_connue_sure(command) and not autorisee():
        destructive = est_destructive(command)
        return {
            "status": "requires_confirmation",
            "command": command,
            "cwd": str(base),
            "reason": "destructive" if destructive else "inconnue",
            "message": (
                ("Commande DESTRUCTIVE. " if destructive else
                 "Commande non reconnue comme sûre. ")
                + "AXON va demander son accord à l'utilisateur : montre la commande "
                  "telle quelle et n'annonce rien comme fait. Tu ne peux pas accorder "
                  "cette autorisation toi-même."),
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
    #
    # Sauf pour le nom de la racine des projets, qui DÉSIGNE cette racine. Deux
    # dossiers peuvent la porter — `~/projets-perso` et `~/Documents/projets-perso`
    # coexistent ici — et le hasard du répertoire courant choisissait alors
    # lequel. Ce que l'utilisateur a configuré tranche : c'est sa déclaration.
    p = Path(path)
    if not p.is_absolute():
        racine = _racine_des_projets()
        p = (racine if racine is not None and path.strip("/") == racine.name
             else (_cwd / path).resolve())
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
