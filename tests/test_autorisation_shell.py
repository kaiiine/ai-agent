"""L'autorisation d'exécuter ne vient jamais du modèle.

`shell_run` portait `confirmed: bool`, que le modèle remplissait lui-même :

    shell_run("rm -rf /tmp/zzz_axon_preuve", confirmed=True)
      → status: ok      dossier supprimé, aucun humain n'a rien vu

Un seul appel. La politique « demander TOUJOURS confirmation » tenait dans une
phrase de docstring adressée au modèle — une obéissance, pas une garantie.

Et la porte, quand elle existait, ne se présentait presque jamais : sur quatorze
formulations destructrices, NEUF n'étaient pas détectées. Construire la serrure
avant de réparer la porte aurait été du théâtre de sécurité.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.agents.shell import autorisation
from src.agents.shell.classification import (
    est_catastrophique,
    est_connue_sure,
    est_destructive,
)


@pytest.fixture(autouse=True)
def magasin_propre():
    autorisation.reinitialiser()
    yield
    autorisation.reinitialiser()


# ── Détection : les formulations qui passaient ───────────────────────────────
@pytest.mark.parametrize("commande", [
    "rm -rf /tmp/x",
    "cd /tmp && rm -rf x",           # le préfixe n'est plus le verbe
    "sudo rm -rf /tmp/x",
    "/bin/rm -rf /tmp/x",            # chemin absolu
    "find /tmp -name '*' -delete",   # option destructrice
    "git -C /repo clean -fdx",       # sous-commande
    "nohup rm -rf /tmp/x",           # enveloppe
    "time rm -rf /tmp/x",
    "X=1 rm -rf /tmp/x",             # affectation en tête
    'bash -c "rm -rf /tmp/x"',       # code en ligne
    'eval "rm -rf /tmp/x"',
    "xargs rm -rf < liste.txt",
    "shred -u /tmp/x",
    "dd if=/dev/zero of=/dev/sda",
])
def test_les_formulations_destructrices_sont_vues(commande):
    assert est_destructive(commande), f"« {commande} » passe encore"


@pytest.mark.parametrize("commande", [
    # HELD-OUT : vocabulaire qui n'a pas servi à construire la détection.
    'ssh vps "rm -rf /var/log"',      # la charge est derrière l'hôte
    "cat liste | xargs -n1 rm -f",
    "docker system prune -af",
    "kubectl delete pod mon-pod",
    "git branch -D main",             # la CASSE de l'argument compte
    "truncate -s 0 important.log",
    "( cd /tmp; rm -rf build )",
    "apt-get purge nginx",
    "npm uninstall react",
    "rsync -a --delete src/ dst/",
])
def test_la_detection_generalise_hors_du_corpus_de_reglage(commande):
    assert est_destructive(commande), f"« {commande} » échappe hors corpus"


@pytest.mark.parametrize("commande", [
    "ls -la", "git status", "pytest tests/ -q", "grep -rn foo src/",
    "npm run build", "python3 script.py", "cd /tmp && ls", "docker ps",
    "find . -name '*.py'", "git log --oneline -5", "make test",
    "git branch -d ancienne",         # minuscule : suppression sûre
])
def test_le_quotidien_ne_declenche_rien(commande):
    """Sur-détecter coûte un clic, mais sur-détecter le quotidien rendrait
    l'agent inutilisable — et un garde qu'on désactive ne protège de rien."""
    assert not est_destructive(commande)
    assert est_connue_sure(commande), f"« {commande} » demanderait une confirmation"


@pytest.mark.parametrize("commande", [
    "rm -rf /", "rm -rf ~", "cd / && rm -rf *", "sudo rm -rf /",
    "/bin/rm -rf /", "nohup rm -rf ~ &", 'bash -c "rm -rf /"', "rm -rf /*",
])
def test_les_cibles_catastrophiques_sont_refusees_meme_avec_accord(commande):
    """Cinq de ces huit passaient : le rempart censé tenir MÊME contre une
    confirmation était le plus facile à contourner."""
    assert est_catastrophique(commande)


@pytest.mark.parametrize("commande", ["rm -rf /tmp/x", "rm -rf build", "rm f.txt"])
def test_une_suppression_legitime_reste_possible(commande):
    assert not est_catastrophique(commande)


def test_un_interprete_avec_du_code_en_ligne_n_est_pas_declare_sur():
    """La limite assumée, traitée honnêtement plutôt que masquée.

    `python3 -c "shutil.rmtree('/')"` ne contient AUCUN verbe shell : aucune
    détection par motif ne peut le voir. On ne prétend donc pas qu'il est sûr —
    il tombe dans « inconnu », donc en confirmation."""
    code = 'python3 -c "import shutil; shutil.rmtree(chr(47))"'
    assert not est_destructive(code), "on ne prétend pas savoir le lire"
    assert not est_connue_sure(code), "…mais on ne le déclare pas sûr pour autant"
    assert est_connue_sure("python3 script.py"), "le quotidien reste fluide"


def test_tous_les_verbes_comptent_pas_seulement_le_premier():
    """`ls && wget http://x | sh` ne devient pas anodin parce qu'il commence
    par `ls`."""
    assert not est_connue_sure("ls && rm -rf /tmp/x")


# ── Le magasin ───────────────────────────────────────────────────────────────
def test_un_accord_ne_sert_qu_une_fois():
    autorisation.accorder("rm -rf /tmp/x")
    assert autorisation.est_autorisee("rm -rf /tmp/x")
    assert not autorisation.est_autorisee("rm -rf /tmp/x"), (
        "un « oui » ne doit pas autoriser toutes les répétitions")


def test_un_accord_n_est_pas_transferable():
    autorisation.accorder("rm -rf /tmp/x")
    assert not autorisation.est_autorisee("rm -rf /tmp/y")


def test_un_accord_perime_ne_vaut_rien():
    autorisation.accorder("rm -rf /tmp/x", duree=-1)
    assert not autorisation.est_autorisee("rm -rf /tmp/x")


def test_une_permission_declaree_ne_se_consomme_pas():
    """Une règle, pas un jeton : une tâche planifiée qui tourne tous les jours
    ne doit pas épuiser sa permission au premier passage."""
    autorisation.declarer("cron:1", ["docker system prune -af"])
    assert autorisation.est_autorisee("docker system prune -af")
    assert autorisation.est_autorisee("docker system prune -af")


def test_retirer_une_source_ne_touche_pas_les_autres():
    autorisation.declarer("cron:1", ["docker system prune -af"])
    autorisation.declarer("cron:2", ["kubectl delete pod x"])
    autorisation.retirer("cron:1")
    assert not autorisation.est_autorisee("docker system prune -af")
    assert autorisation.est_autorisee("kubectl delete pod x")


# ── Bout en bout ─────────────────────────────────────────────────────────────
def test_le_modele_ne_peut_plus_forger_son_autorisation():
    """LE test. `confirmed=True` était le contournement ; il ne doit plus exister
    ni comme paramètre, ni comme effet."""
    from src.agents.shell.tools import shell_run

    assert "confirmed" not in shell_run.args_schema.model_json_schema()["properties"], (
        "le paramètre est de retour dans le schéma exposé au modèle")

    temoin = Path("/tmp/zzz_axon_autorisation")
    temoin.mkdir(exist_ok=True)
    (temoin / "f.txt").touch()
    try:
        r = shell_run.invoke({"command": f"rm -rf {temoin}", "confirmed": True})
        assert r["status"] == "requires_confirmation"
        assert temoin.is_dir(), "la commande s'est exécutée malgré le refus"
    finally:
        os.system(f"rm -rf {temoin}")


def test_un_accord_humain_laisse_passer_une_seule_fois():
    from src.agents.shell.tools import shell_run

    temoin = Path("/tmp/zzz_axon_accord")
    temoin.mkdir(exist_ok=True)
    try:
        autorisation.accorder(f"rm -rf {temoin}")
        assert shell_run.invoke({"command": f"rm -rf {temoin}"})["status"] == "ok"
        assert not temoin.exists()

        temoin.mkdir()
        assert shell_run.invoke({"command": f"rm -rf {temoin}"})["status"] == \
            "requires_confirmation", "l'accord a resservi"
        assert temoin.is_dir()
    finally:
        os.system(f"rm -rf {temoin}")


def test_une_commande_inconnue_demande_un_accord():
    """Le défaut inversé : inconnu → confirmation, pas inconnu → exécution."""
    from src.agents.shell.tools import shell_run

    r = shell_run.invoke({"command": "binaire_jamais_vu --option"})
    assert r["status"] == "requires_confirmation"
    assert r["reason"] == "inconnue"


def test_le_quotidien_passe_sans_frottement():
    from src.agents.shell.tools import shell_run

    for commande in ("echo bonjour", "ls /tmp", "git status"):
        assert shell_run.invoke({"command": commande})["status"] in ("ok", "error"), (
            f"« {commande} » demande une confirmation")


def test_un_accord_n_est_consomme_qu_une_fois_PAR_APPEL():
    """L'accord traverse plusieurs gardes dans le même appel — il ne doit pas
    s'épuiser en chemin.

    Vécu : `ssh vps "monbinaire > /etc/motd"` franchissait la branche d'écriture,
    qui consommait le « oui » ; la porte générale, consultée juste après, ne
    trouvait plus rien et refusait. L'utilisateur répondait « oui », rien ne
    partait, le modèle redemandait — une boucle de questions née d'un correctif
    de sécurité. Un correctif qui boucle est pire que le défaut qu'il corrige.
    """
    from src.agents.shell.classification import est_connue_sure
    from src.agents.shell.tools import shell_run

    commande = 'ssh vps "monbinaire_inconnu > /etc/motd"'
    # Le cas n'a d'intérêt que s'il traverse VRAIMENT les deux gardes : une
    # écriture (donc la branche `ecriture`) ET un verbe non reconnu (donc la
    # porte générale).
    assert not est_connue_sure(commande)

    autorisation.accorder(commande)
    statut = shell_run.invoke({"command": commande})["status"]
    assert statut != "requires_confirmation", (
        "l'accord a été consommé par un garde puis manqué par le suivant")
