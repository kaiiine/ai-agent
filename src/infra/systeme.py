"""Ce qu'est la machine, décidé une fois par processus.

Un modèle qui doit lancer `uname` et lire `/etc/os-release` avant de proposer une
commande paie un aller-retour d'outil pour un résultat qui ne change jamais de la
session. Pire, il peut oublier de le faire — et le prompt portait justement un
`pacman -Qm` en dur, c'est-à-dire l'hypothèse Arch câblée pour tout le monde.

La détection est déterministe : elle appartient au code, pas au raisonnement.

Elle s'appuie d'abord sur les BINAIRES PRÉSENTS, pas sur le nom de la distribution.
`/etc/os-release` dit ce que le système prétend être ; `shutil.which` dit ce qu'on
peut réellement exécuter. Les deux divergent dans exactement le cas que l'on
craint — un conteneur Debian lancé depuis une machine Arch — et c'est le second
qui a raison.
"""
from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from functools import lru_cache

#: gestionnaire → (installer, mettre à jour, chercher). Le premier trouvé gagne.
_GESTIONNAIRES: tuple[tuple[str, str, str, str], ...] = (
    ("pacman", "pacman -S <pkg>",   "pacman -Syu",              "pacman -Ss <motif>"),
    ("apt",    "apt install <pkg>", "apt update && apt upgrade", "apt search <motif>"),
    ("dnf",    "dnf install <pkg>", "dnf upgrade",              "dnf search <motif>"),
    ("zypper", "zypper install <pkg>", "zypper update",         "zypper search <motif>"),
    ("apk",    "apk add <pkg>",     "apk upgrade",              "apk search <motif>"),
    ("brew",   "brew install <pkg>", "brew upgrade",            "brew search <motif>"),
    ("winget", "winget install <pkg>", "winget upgrade --all",  "winget search <motif>"),
)

#: assistants AUR, dans l'ordre de préférence.
_AUR = ("yay", "paru")


@dataclass(frozen=True)
class ContexteSysteme:
    famille: str          # linux · macos · windows
    distro: str           # arch, debian, fedora… ou "" si indéterminé
    gestionnaire: str     # pacman, apt, brew… ou "" si aucun n'est présent
    installer: str
    mettre_a_jour: str
    chercher: str
    aur: str              # yay, paru, ou ""
    services: str         # systemctl, brew services, Restart-Service ou ""
    shell: str

    def resume(self) -> str:
        """Le bloc injecté dans le prompt : uniquement la colonne qui s'applique.

        La table complète des cinq OS pèse ~900 tokens pour n'en servir qu'un
        cinquième. Celle-ci en pèse moins de cent.
        """
        lignes = [f"━━ MACHINE ━━",
                  f"{self.famille}"
                  + (f" / {self.distro}" if self.distro else "")
                  + f" · shell {self.shell}"]
        if self.gestionnaire:
            lignes.append(f"install {self.installer} · update {self.mettre_a_jour}"
                          f" · search {self.chercher}")
            if self.aur:
                lignes.append(f"AUR : {self.aur} -S <pkg>")
        else:
            lignes.append("Aucun gestionnaire de paquets détecté — demander avant "
                          "d'en supposer un.")
        if self.services:
            lignes.append(f"services {self.services}")
        lignes.append("Ne jamais proposer la syntaxe d'un AUTRE gestionnaire que "
                      "celui-ci. En cas de « command not found », c'est ce bloc qui "
                      "est périmé : re-détecter plutôt que deviner un autre binaire.")
        return "\n".join(lignes)


def _distro_linux() -> str:
    """L'`ID` de /etc/os-release, ou son `ID_LIKE` si l'ID est inconnu.

    EndeavourOS, Manjaro et CachyOS déclarent `ID_LIKE=arch` : sans ce repli,
    chacun serait une distribution inconnue de plus.
    """
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            champs = dict(
                ligne.strip().split("=", 1)
                for ligne in f if "=" in ligne and not ligne.startswith("#"))
    except OSError:
        return ""
    def propre(cle: str) -> str:
        return champs.get(cle, "").strip('"\'').split()[0] if champs.get(cle) else ""
    return propre("ID") or propre("ID_LIKE")


def _version(famille: str) -> str:
    """Ce qui identifie le système, dans le vocabulaire de sa propre famille.

    `platform.release()` rend le noyau : sous macOS c'est « 24.1.0 », le numéro
    de Darwin, qui ne dit rien à personne — la version produit est « 15.1 ».
    Sous Windows il rend « 10 » pour Windows 10 comme pour Windows 11.
    """
    if famille == "macos":
        produit = platform.mac_ver()[0]
        return f"macOS {produit}" if produit else "macOS"
    if famille == "windows":
        edition = platform.win32_edition() if hasattr(platform, "win32_edition") else ""
        release = platform.release()
        build = platform.version().rsplit(".", 1)[-1]
        # Windows 11 se déclare « 10 » : seul le numéro de build les sépare.
        if release == "10" and build.isdigit() and int(build) >= 22000:
            release = "11"
        return f"Windows {release}" + (f" {edition}" if edition else "")
    return _distro_linux()


def _shell(famille: str) -> str:
    """Le shell RÉELLEMENT en place, pas celui qu'on suppose à l'OS.

    `$SHELL` n'existe pas sous Windows, où l'ancienne version repliait sur
    « powershell » en dur — ce qui effaçait la différence entre cmd,
    PowerShell 5 et pwsh 7, dont les syntaxes ne sont pas interchangeables.
    """
    import os
    if famille == "windows":
        # Un shell POSIX sous Windows (Git Bash, MSYS, WSL) pose $SHELL : il a
        # priorité, c'est lui qui interprétera la commande.
        posix = os.environ.get("SHELL", "")
        if posix:
            return posix.rsplit("/", 1)[-1]
        if shutil.which("pwsh"):
            return "pwsh"
        if os.environ.get("PSModulePath"):
            return "powershell"
        return os.environ.get("ComSpec", "cmd").rsplit("\\", 1)[-1]
    return (os.environ.get("SHELL", "") or "").rsplit("/", 1)[-1] or "?"


def _services(famille: str) -> str:
    """Comment on redémarre un service et où on lit ses logs.

    Testé par la PRÉSENCE de `systemctl`, pas par la famille : un conteneur
    Linux sans init n'en a pas, et macOS peut en avoir un via une VM.
    """
    if famille == "windows":
        return "Restart-Service <svc> · Get-Service <svc> · Get-EventLog -LogName Application"
    if shutil.which("systemctl"):
        return ("systemctl restart <svc> (--user si unité utilisateur)"
                " · journalctl -u <svc> -e")
    if famille == "macos":
        base = "launchctl kickstart -k <domaine>/<svc> · log show --predicate ..."
        return f"brew services restart <svc> · {base}" if shutil.which("brew") else base
    return ""


@lru_cache(maxsize=1)
def contexte() -> ContexteSysteme:
    """Détecté une seule fois par processus. Voir `oublier()` pour re-détecter."""
    systeme = platform.system().lower()
    famille = {"darwin": "macos", "windows": "windows"}.get(systeme, "linux")

    gestionnaire = installer = maj = chercher = ""
    for nom, i, u, s in _GESTIONNAIRES:
        if shutil.which(nom):
            gestionnaire, installer, maj, chercher = nom, i, u, s
            break

    aur = ""
    if gestionnaire == "pacman":
        aur = next((a for a in _AUR if shutil.which(a)), "")

    return ContexteSysteme(
        famille=famille,
        distro=_version(famille),
        gestionnaire=gestionnaire, installer=installer,
        mettre_a_jour=maj, chercher=chercher, aur=aur,
        services=_services(famille), shell=_shell(famille),
    )


def oublier() -> None:
    """Vide le cache — pour les tests, et pour le cas où l'environnement change."""
    contexte.cache_clear()
