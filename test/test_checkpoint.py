"""La persistance des threads : ce qu'on écrit doit survivre à une interruption.

Ce fichier n'existait pas, et le module portait un défaut à deux moitiés qui se
nourrissaient l'une l'autre :

  · `save_thread_cwd` lisait la table des cwd avec un `except: pass`. JSON
    illisible → `data` restait à {} → et le fichier était RÉÉCRIT avec cette
    table vide. Une seule lecture ratée effaçait le cwd de tous les autres
    threads. Mesuré sur trois, il en restait un ; le fichier réel de la machine
    en contenait 286 ;
  · l'écriture se faisait par `write_text`, qui TRONQUE la cible avant d'écrire.
    Un processus tué au mauvais moment produisait exactement le JSON à moitié
    écrit que la lecture suivante ne savait pas relire.

La première moitié détruisait ce que la seconde cassait. Elles sont corrigées
ensemble : écriture atomique, et fichier illisible mis de côté plutôt qu'écrasé.

Une suspicion a été mesurée puis ABANDONNÉE : `list_threads` trie sur
`MAX(checkpoint_id)` et non sur l'horodatage, ce qui semblait arbitraire. Les ids
de LangGraph sont des UUID v6, ordonnés par le temps par construction — vérifié
sur les douze threads les plus récents de la base réelle, l'ordre du tri suit
exactement celui des horodatages. Il n'y a rien à corriger là.
"""
import json

import pytest


@pytest.fixture
def cwds(tmp_path, monkeypatch):
    """Redirige la table des cwd vers un fichier temporaire.

    Le module ouvre une connexion SQLite sur ~/.axon/memory.db dès l'import ;
    seuls les chemins de fichiers sont détournés, jamais la base.
    """
    from src.infra import checkpoint

    fichier = tmp_path / "thread_cwds.json"
    monkeypatch.setattr(checkpoint, "_CWD_FILE", fichier)
    return checkpoint, fichier


# ── Une lecture ratée ne doit rien détruire ───────────────────────────────────
def test_un_json_illisible_n_efface_pas_les_autres_threads(cwds):
    """Le défaut central. Avant : trois threads enregistrés, un fichier tronqué,
    un save de plus — et il n'en restait qu'un."""
    checkpoint, fichier = cwds
    checkpoint.save_thread_cwd("thread-A", "/projets/alpha")
    checkpoint.save_thread_cwd("thread-B", "/projets/beta")

    fichier.write_text('{"thread-A": "/projets/alpha", "thread-B": ')  # écriture interrompue
    checkpoint.save_thread_cwd("thread-C", "/projets/gamma")

    corrompus = list(fichier.parent.glob(f"{fichier.name}.corrompu-*"))
    assert corrompus, "le fichier illisible doit rester récupérable, pas être écrasé"
    assert '"thread-A"' in corrompus[0].read_text()


def test_une_table_qui_n_est_pas_un_objet_est_traitee_comme_corrompue(cwds):
    """`json.loads("[]")` réussit et rend une liste : sans contrôle de type,
    `data[thread_id] = cwd` lèverait un TypeError en pleine sauvegarde."""
    checkpoint, fichier = cwds
    fichier.write_text("[1, 2, 3]")

    checkpoint.save_thread_cwd("thread-A", "/projets/alpha")

    assert checkpoint.load_thread_cwd("thread-A") == "/projets/alpha"


# ── L'écriture est atomique ───────────────────────────────────────────────────
def test_l_ecriture_passe_par_un_rename(cwds):
    """Ce n'est pas un détail de style : `write_text` tronque la cible AVANT
    d'écrire, et c'est ce moignon qui déclenchait la destruction ci-dessus."""
    checkpoint, fichier = cwds
    checkpoint.save_thread_cwd("thread-A", "/projets/alpha")

    assert not list(fichier.parent.glob("*.tmp")), "aucun temporaire ne doit rester"
    assert json.loads(fichier.read_text()) == {"thread-A": "/projets/alpha"}


def test_le_dernier_thread_s_ecrit_aussi_atomiquement(tmp_path, monkeypatch):
    from src.infra import checkpoint

    fichier = tmp_path / "last_thread"
    monkeypatch.setattr(checkpoint, "_LAST_FILE", fichier)
    checkpoint.save_last_thread("thread-42")

    assert checkpoint.load_last_thread() == "thread-42"
    assert not list(tmp_path.glob("*.tmp"))


# ── Le comportement nominal ne bouge pas ──────────────────────────────────────
def test_plusieurs_threads_coexistent(cwds):
    checkpoint, fichier = cwds
    for nom, chemin in [("A", "/p/alpha"), ("B", "/p/beta"), ("C", "/p/gamma")]:
        checkpoint.save_thread_cwd(nom, chemin)

    assert json.loads(fichier.read_text()) == {
        "A": "/p/alpha", "B": "/p/beta", "C": "/p/gamma"}


def test_reecrire_un_thread_remplace_son_cwd(cwds):
    checkpoint, _ = cwds
    checkpoint.save_thread_cwd("A", "/p/ancien")
    checkpoint.save_thread_cwd("A", "/p/nouveau")

    assert checkpoint.load_thread_cwd("A") == "/p/nouveau"


def test_un_thread_inconnu_ne_rend_rien(cwds):
    checkpoint, _ = cwds
    checkpoint.save_thread_cwd("A", "/p/alpha")

    assert checkpoint.load_thread_cwd("inconnu") is None


def test_sans_fichier_la_lecture_ne_casse_pas(cwds):
    checkpoint, _ = cwds

    assert checkpoint.load_thread_cwd("A") is None


def test_un_dernier_thread_vide_vaut_absence(tmp_path, monkeypatch):
    """Un fichier présent mais vide ne doit pas rendre la chaîne vide comme un
    identifiant valide — elle serait utilisée comme thread_id."""
    from src.infra import checkpoint

    fichier = tmp_path / "last_thread"
    monkeypatch.setattr(checkpoint, "_LAST_FILE", fichier)
    fichier.write_text("   \n")

    assert checkpoint.load_last_thread() is None
