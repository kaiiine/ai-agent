"""La machine est détectée, jamais supposée (src/infra/systeme.py).

Le prompt portait `pacman -Qm` en dur : l'hypothèse Arch était câblée pour tout
le monde, y compris pour un conteneur Debian lancé depuis une machine Arch. Ces
tests gardent les trois propriétés qui rendent ce genre de faute impossible :

  - la détection s'appuie sur les BINAIRES PRÉSENTS, pas sur le nom déclaré par
    la distribution — c'est la seule source qui ait raison quand les deux
    divergent ;
  - le prompt ne cite JAMAIS la syntaxe d'un gestionnaire qui n'est pas là ;
  - le bloc n'est injecté que si des outils shell sont routés.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.infra.systeme import ContexteSysteme, _distro_linux, contexte, oublier


@pytest.fixture(autouse=True)
def _cache_propre():
    oublier()
    yield
    oublier()


def test_la_detection_est_faite_une_seule_fois():
    """Un aller-retour d'outil par session pour un résultat immuable serait déjà
    trop ; le recalculer à chaque appel de prompt le serait tout autant."""
    assert contexte() is contexte()


def test_le_resume_ne_cite_que_le_gestionnaire_detecte():
    """La faute d'origine, retournée en invariant : aucune syntaxe étrangère."""
    ctx = contexte()
    resume = ctx.resume()
    autres = {"pacman", "apt", "dnf", "zypper", "apk", "brew", "winget"} - {ctx.gestionnaire}
    intrus = [g for g in autres if f"{g} " in resume]
    assert not intrus, f"le résumé cite des gestionnaires absents : {intrus}"


def test_le_resume_reste_court():
    """Une seule colonne, pas la table des cinq OS — celle-ci pèserait ~900
    tokens pour n'en servir qu'un cinquième."""
    assert len(contexte().resume()) < 700


def test_un_systeme_sans_gestionnaire_le_dit_au_lieu_d_en_inventer_un():
    nu = ContexteSysteme(famille="linux", distro="", gestionnaire="", installer="",
                         mettre_a_jour="", chercher="", aur="", services="", shell="sh")
    resume = nu.resume()
    assert "Aucun gestionnaire" in resume
    for g in ("pacman", "apt", "dnf", "brew", "winget"):
        assert g not in resume


def test_une_distribution_derivee_est_rattachee_a_sa_famille(tmp_path, monkeypatch):
    """EndeavourOS, Manjaro et CachyOS déclarent `ID_LIKE=arch`. Sans ce repli,
    chacune serait une distribution inconnue de plus."""
    fichier = tmp_path / "os-release"
    fichier.write_text('ID=endeavouros\nID_LIKE=arch\nNAME="EndeavourOS"\n')
    vrai_open = open

    def faux_open(chemin, *a, **kw):
        if str(chemin) == "/etc/os-release":
            return vrai_open(fichier, *a, **kw)
        return vrai_open(chemin, *a, **kw)

    monkeypatch.setattr("builtins.open", faux_open)
    assert _distro_linux() == "endeavouros"

    fichier.write_text('ID_LIKE=arch\n')
    assert _distro_linux() == "arch", "repli sur ID_LIKE absent"


def test_une_os_release_absente_ne_fait_pas_tomber_la_detection(monkeypatch):
    def refuse(chemin, *a, **kw):
        raise OSError("pas de /etc/os-release")

    monkeypatch.setattr("builtins.open", refuse)
    assert _distro_linux() == ""


# ── Injection dans le prompt ─────────────────────────────────────────────────
def _prompt(outils):
    from src.llm.prompts import build_system_prompt
    return build_system_prompt(outils, date.today().isoformat(), "test")


def test_le_bloc_machine_accompagne_les_outils_shell():
    assert "━━ MACHINE ━━" in _prompt(["shell_run", "shell_cd"])


def test_le_bloc_machine_n_est_pas_paye_sans_outil_shell():
    """Conditionnel comme le reste : un thread qui résume des mails n'a pas à
    porter la syntaxe de pacman."""
    assert "━━ MACHINE ━━" not in _prompt(["gmail_summarize"])


def test_le_prompt_ne_code_en_dur_aucune_distribution():
    """Le test qui aurait attrapé la faute d'origine. `_SHELL` citait
    `pacman -Qm` en exemple, ce qui apprenait Arch à toutes les machines."""
    from src.llm.prompts import orchestrateur

    for bloc in (orchestrateur._SHELL, orchestrateur._CORE):
        for commande in ("pacman -", "apt install", "apt-get", "dnf install",
                         "brew install", "winget install"):
            assert commande not in bloc, f"« {commande} » codé en dur dans le prompt"


# ── Généralité : la même détection sur d'autres machines ─────────────────────
#
# Ces tests SIMULENT macOS, Windows, Debian et Alpine. Sans eux, « ça s'adapte »
# resterait une affirmation vérifiée sur une seule machine — celle du
# développeur, sous Arch, où tout marche par construction.
def _simuler(monkeypatch, systeme: str, binaires: set[str], env: dict | None = None):
    import os as _os
    import platform as _pf
    import shutil as _sh

    monkeypatch.setattr(_pf, "system", lambda: systeme)
    monkeypatch.setattr("src.infra.systeme.shutil.which",
                        lambda nom, *a, **k: f"/usr/bin/{nom}" if nom in binaires else None)
    monkeypatch.setattr(_os, "environ", dict(env or {}))
    oublier()


@pytest.mark.parametrize("systeme, binaires, env, attendus, absents", [
    ("Darwin", {"brew"}, {"SHELL": "/bin/zsh"},
     ["brew install <pkg>", "brew upgrade", "brew services restart"], ["pacman", "apt", "winget"]),
    ("Windows", {"winget"}, {"PSModulePath": "C:\\Modules"},
     ["winget install <pkg>", "Restart-Service"], ["pacman", "apt", "brew", "systemctl"]),
    ("Linux", {"apt", "systemctl"}, {"SHELL": "/bin/bash"},
     ["apt install <pkg>", "apt update && apt upgrade", "systemctl restart"], ["pacman", "brew", "winget"]),
    ("Linux", {"apk"}, {"SHELL": "/bin/sh"},
     ["apk add <pkg>", "apk upgrade"], ["pacman", "apt", "systemctl"]),
])
def test_la_detection_suit_la_machine(monkeypatch, systeme, binaires, env, attendus, absents):
    _simuler(monkeypatch, systeme, binaires, env)
    resume = contexte().resume()
    for attendu in attendus:
        assert attendu in resume, f"{systeme}/{binaires} : « {attendu} » manquant\n{resume}"
    for absent in absents:
        assert absent not in resume, f"{systeme}/{binaires} : « {absent} » ne devrait pas être là"


def test_un_shell_posix_sous_windows_gagne_sur_powershell(monkeypatch):
    """Git Bash, MSYS ou WSL posent $SHELL. C'est lui qui interprétera la
    commande, pas PowerShell — et leurs syntaxes ne sont pas interchangeables."""
    _simuler(monkeypatch, "Windows", {"winget"},
             {"SHELL": "/usr/bin/bash", "PSModulePath": "C:\\Modules"})
    assert contexte().shell == "bash"


def test_pwsh_prime_sur_powershell_5(monkeypatch):
    _simuler(monkeypatch, "Windows", {"winget", "pwsh"}, {"PSModulePath": "C:\\Modules"})
    assert contexte().shell == "pwsh"


def test_macos_donne_sa_version_produit_et_non_celle_du_noyau(monkeypatch):
    """`platform.release()` rend « 24.1.0 », le numéro de Darwin, que personne ne
    reconnaît. La version produit est « 15.1 »."""
    import platform as _pf
    _simuler(monkeypatch, "Darwin", {"brew"}, {"SHELL": "/bin/zsh"})
    monkeypatch.setattr(_pf, "mac_ver", lambda: ("15.1", ("", "", ""), "arm64"))
    oublier()
    assert contexte().distro == "macOS 15.1"


def test_une_machine_sans_gestionnaire_ne_propose_rien(monkeypatch):
    """Le cas qui compte pour la sûreté : ne rien savoir doit se dire, pas se
    combler par le gestionnaire de la machine du développeur."""
    _simuler(monkeypatch, "Linux", set(), {"SHELL": "/bin/sh"})
    resume = contexte().resume()
    assert "Aucun gestionnaire" in resume
    for g in ("pacman", "apt", "dnf", "brew", "winget", "apk", "zypper"):
        assert g not in resume


# ── Les garde-fous ne dépendent d'aucun OS ───────────────────────────────────
@pytest.mark.parametrize("commande", [
    # POSIX
    "rm -rf /", "sudo rm -rf ~", "dd if=/dev/zero of=/dev/sda", "mkfs.ext4 /dev/sda1",
    "apt purge nginx", "brew uninstall node", "pacman -R firefox",
    # Windows — PowerShell et cmd
    "Remove-Item -Recurse -Force C:\\Users", "ri C:\\", "del /f /s /q C:\\",
    "rd /s /q .", "Format-Volume -DriveLetter C", "diskpart", "winget uninstall vlc",
    # VCS
    "git reset --hard", "git push --force origin main",
])
def test_toute_commande_destructive_demande_confirmation(commande):
    """La liste était purement POSIX : sur Windows, `Remove-Item -Recurse -Force`
    et `del /f /s /q C:\\` passaient SANS confirmation. Le filet disparaissait en
    silence en changeant de machine.

    L'UNION des vocabulaires, jamais celui de l'OS détecté : une détection qui se
    trompe (conteneur, WSL, shell POSIX sous Windows) désarmerait le garde. Une
    union ne se trompe que dans le sens sûr.
    """
    from src.agents.shell.tools import _is_destructive
    assert _is_destructive(commande), f"« {commande} » passe sans confirmation"


@pytest.mark.parametrize("commande", [
    "ls -la", "git status", "cat README.md", "pytest -q",
    "npm run build", "docker ps", "Get-Process", "dir",
])
def test_une_commande_inoffensive_ne_declenche_rien(commande):
    from src.agents.shell.tools import _is_destructive, _is_catastrophic_rm
    assert not _is_destructive(commande)
    assert not _is_catastrophic_rm(commande)


@pytest.mark.parametrize("commande", [
    "rm -rf /", "rm -rf ~", "rm -rf .", "rm -rf *",
    "Remove-Item C:\\", "ri $env:USERPROFILE", "del /f /s /q C:\\", "rd /s /q .",
])
def test_une_cible_catastrophique_est_refusee_sur_tout_os(commande):
    from src.agents.shell.tools import _is_catastrophic_rm
    assert _is_catastrophic_rm(commande), f"« {commande} » n'est pas reconnue"


@pytest.mark.parametrize("code, sortie, attendu", [
    (127, "", True),                                        # POSIX
    (9009, "", True),                                       # cmd.exe
    (1, "'foo' n'est pas reconnu en tant que commande", True),
    (1, "CommandNotFoundException", True),                  # PowerShell
    (127, "[rtk: No such file or directory]", True),        # rtk écrit sur stdout
    (1, "3 tests failed", False),
    (0, "ok", False),
])
def test_commande_introuvable_se_reconnait_sur_tout_shell(code, sortie, attendu):
    """La condition exigeait aussi une sortie VIDE. Avec `rtk` installé elle ne
    l'est jamais, si bien que toute cette branche était morte sur la machine où
    elle comptait le plus."""
    from src.agents.shell.tools import _commande_introuvable
    assert _commande_introuvable(code, sortie) is attendu
