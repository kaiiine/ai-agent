"""Un thread neuf doit l'être vraiment.

Symptôme : « analyse tous mes fichiers » dans un thread NEUF a produit l'analyse
d'`axon-landing` seul. Ce n'était pas une mauvaise compréhension — le modèle
avait reçu 2 065 tokens de décisions sur ce projet AVANT la question, et « mes
fichiers » ne pouvait plus vouloir dire autre chose.

La chaîne, mesurée :

    `_cwd` est une globale du PROCESSUS, pas du thread
      → `/new` ne la touchait pas (`/history` et le démarrage, si)
        → `_load_axon_memory()` cherche `.axon/memory/` DEPUIS ce répertoire
          → le prompt d'un thread neuf portait la mémoire du projet précédent

Ce que le correctif ne casse pas, et c'est le point qui comptait : le répertoire
est déjà persisté PAR THREAD (`app.py` l'écrit après chaque échange, `/history`
le restaure). Remettre `/new` à `$HOME` n'efface donc rien — chaque ancien thread
retrouve son projet au retour.
"""
from pathlib import Path

import pytest

from src.agents.shell.tools import get_cwd, set_cwd
from src.infra.checkpoint import load_thread_cwd, save_thread_cwd
from src.ui.commands import handle_slash
from src.ui.config import SessionConfig


@pytest.fixture(autouse=True)
def _repartir_de_la_maison():
    """Le cwd est global au processus : sans ça, un test contamine le suivant."""
    avant = get_cwd()
    yield
    set_cwd(avant)


def _cfg(thread_id: str) -> SessionConfig:
    c = SessionConfig()
    c.thread_id = thread_id
    return c


# ── Le correctif ──────────────────────────────────────────────────────────────
def test_new_remet_le_repertoire_a_la_maison(tmp_path):
    """Sans ça, un thread neuf hérite du dossier du précédent — et donc de sa
    mémoire projet, qui arrive AVANT la question de l'utilisateur."""
    set_cwd(tmp_path)
    assert get_cwd() == tmp_path.resolve()

    handle_slash("/new", {"messages": []}, _cfg("peu-importe"))

    assert get_cwd() == Path.home()


def test_new_persiste_le_repertoire_du_nouveau_thread(tmp_path):
    """Il doit être écrit, pas seulement appliqué : sinon revenir sur ce thread
    plus tard ne restaure rien."""
    set_cwd(tmp_path)
    cfg = _cfg("ancien")

    handle_slash("/new", {"messages": []}, cfg)

    assert load_thread_cwd(cfg.thread_id) == str(Path.home())


# ── Ce que le correctif ne doit PAS casser ────────────────────────────────────
def test_un_ancien_thread_garde_son_projet(tmp_path):
    """La question posée avant d'accepter le correctif : revenir sur un thread
    de code doit y ramener."""
    projet = tmp_path / "mon-projet"
    projet.mkdir()
    save_thread_cwd("thread-code", str(projet))
    set_cwd(projet)

    handle_slash("/new", {"messages": []}, _cfg("thread-code"))

    assert get_cwd() == Path.home(), "le thread NEUF repart à la maison"
    assert load_thread_cwd("thread-code") == str(projet), (
        "l'ancien thread garde le sien sur disque")


def test_le_retour_sur_un_ancien_thread_restaure_son_repertoire(tmp_path):
    """Le geste que fait `/history` — vérifié bout en bout."""
    projet = tmp_path / "mon-projet"
    projet.mkdir()
    save_thread_cwd("thread-code", str(projet))
    set_cwd(Path.home())

    sauvegarde = load_thread_cwd("thread-code")
    if sauvegarde:
        set_cwd(sauvegarde)

    assert get_cwd() == projet.resolve()


def test_chaque_thread_a_son_propre_repertoire(tmp_path):
    """Rien n'est partagé : c'est ce qui rend le reset de `/new` sans danger."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    save_thread_cwd("t-a", str(a))
    save_thread_cwd("t-b", str(b))

    assert load_thread_cwd("t-a") == str(a)
    assert load_thread_cwd("t-b") == str(b)


# ── L'injection ne doit plus être silencieuse ─────────────────────────────────
def test_l_injection_de_memoire_projet_est_annoncee():
    """Elle n'était signalée nulle part : l'utilisateur ne pouvait pas savoir
    qu'Axon avait un projet en tête, ni pourquoi sa réponse s'y limitait."""
    import inspect

    from src.llm.prompts import orchestrateur

    source = inspect.getsource(orchestrateur.build_system_prompt)

    assert "_signaler_memoire_projet()" in source


def test_le_signalement_ne_casse_jamais_le_tour():
    """Un affichage décoratif qui lève ferait perdre le tour entier."""
    from src.llm.prompts.orchestrateur import _signaler_memoire_projet

    _signaler_memoire_projet()


# ── La portée vient de la demande ─────────────────────────────────────────────
def test_le_prompt_dit_que_la_demande_fixe_la_portee():
    from datetime import date

    from src.llm.prompts import build_system_prompt

    p = build_system_prompt(["local_read_file"], date.today().isoformat(),
                            "kaine", lang="fr")

    assert "the request sets the scope, never the current directory" in p
    assert "Never silently narrow a machine-wide request" in p


def test_la_regle_de_portee_suit_les_outils_de_fichiers():
    """Elle vit dans `_FILES` : sans outil de fichier, elle n'a rien à cadrer."""
    from datetime import date

    from src.llm.prompts import build_system_prompt

    nu = build_system_prompt(["get_current_time"], date.today().isoformat(),
                             "kaine", lang="fr")

    assert "SCOPE —" not in nu
