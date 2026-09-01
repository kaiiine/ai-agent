"""Un modèle qui sait où il est n'a pas besoin qu'on lui interdise de se perdre.

Vécu, sur « analyse le projet ai-agent : qu'est-ce qui appelle reviser ? » :
`shell_pwd`, `shell_ls`, `shell_cd projets-perso`, puis un grep dans
`auratis-studio` — un projet sans rapport. Trois causes, aucune de désobéissance :

  · le répertoire de travail valait `$HOME`, en dur, quel que soit l'endroit d'où
    AXON avait été lancé — « ce projet » n'avait donc aucun référent ;
  · rien, dans le prompt, ne disait au modèle où il se trouvait ;
  · `~/projets-perso` et `~/Documents/projets-perso` coexistent sur cette
    machine, et `shell_cd projets-perso` tombait sur le premier venu.

On répare en donnant des FAITS, pas des règles : le lieu de lancement, le lieu
courant, la racine déclarée. Ce qu'il sait, il n'a pas à le chercher.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.shell import tools as shell
from src.llm.prompts.orchestrateur import _ou_tu_es


@pytest.fixture(autouse=True)
def _cwd_restaure():
    avant = shell.get_cwd()
    yield
    shell.set_cwd(str(avant))


# ── le lieu de lancement ──────────────────────────────────────────────────────
def test_axon_demarre_la_ou_on_le_lance(monkeypatch, tmp_path):
    """C'était `$HOME` en dur. Lancer depuis un projet, c'est déjà dire lequel."""
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))

    assert shell._repertoire_de_lancement() == tmp_path


def test_la_racine_du_disque_ne_fait_pas_un_projet(monkeypatch):
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: Path("/")))

    assert shell._repertoire_de_lancement() == Path.home()


def test_un_repertoire_disparu_ne_casse_pas_le_demarrage(monkeypatch):
    def _explose(cls):
        raise OSError("répertoire supprimé sous nos pieds")

    monkeypatch.setattr(Path, "cwd", classmethod(_explose))

    assert shell._repertoire_de_lancement() == Path.home()


# ── la racine déclarée tranche l'homonymie ────────────────────────────────────
def test_le_nom_de_la_racine_designe_la_racine_configuree(tmp_path, monkeypatch):
    """Deux dossiers peuvent porter ce nom ; ce que l'utilisateur a configuré
    tranche, au lieu du hasard du répertoire courant."""
    vraie = tmp_path / "ailleurs" / "projets"
    vraie.mkdir(parents=True)
    piege = tmp_path / "maison" / "projets"          # l'homonyme, en relatif
    piege.mkdir(parents=True)
    monkeypatch.setattr("src.utils.paths.get_projects_dir", lambda: vraie)
    shell.set_cwd(str(tmp_path / "maison"))

    resultat = shell.shell_cd.invoke({"path": "projets"})

    assert Path(resultat["cwd"]) == vraie


def test_un_sous_dossier_ordinaire_reste_relatif(tmp_path, monkeypatch):
    """La règle ne vaut que pour le nom de la racine — sinon `cd src` deviendrait
    imprévisible."""
    racine = tmp_path / "projets"
    racine.mkdir()
    ici = tmp_path / "ici" / "src"
    ici.mkdir(parents=True)
    monkeypatch.setattr("src.utils.paths.get_projects_dir", lambda: racine)
    shell.set_cwd(str(tmp_path / "ici"))

    resultat = shell.shell_cd.invoke({"path": "src"})

    assert Path(resultat["cwd"]) == ici


# ── le fait dit au modèle ─────────────────────────────────────────────────────
def test_le_projet_courant_est_nomme(monkeypatch, tmp_path):
    racine = tmp_path / "projets"
    projet = racine / "mon-appli"
    projet.mkdir(parents=True)
    monkeypatch.setattr("src.utils.paths.get_projects_dir", lambda: racine)
    shell.set_cwd(str(projet))

    dit = _ou_tu_es()

    assert "Current project: mon-appli" in dit
    assert '"this project"' in dit


def test_hors_dun_projet_on_ne_nomme_rien(monkeypatch, tmp_path):
    """Se taire vaut mieux que désigner au hasard — c'est ce hasard qui l'avait
    envoyé dans `auratis-studio`."""
    racine = tmp_path / "projets"
    racine.mkdir(parents=True)
    monkeypatch.setattr("src.utils.paths.get_projects_dir", lambda: racine)
    shell.set_cwd(str(tmp_path))

    dit = _ou_tu_es()

    assert "Current project" not in dit
    assert str(racine) in dit


def test_le_lieu_est_un_fait_pas_une_consigne():
    """Une règle de plus lui interdirait de se tromper ; un fait lui évite d'avoir
    à deviner. Le bloc ne doit donc contenir aucun impératif."""
    dit = _ou_tu_es()

    for consigne in ("must", "never", "always", "❌", "→"):
        assert consigne not in dit, consigne


def test_le_lieu_entre_dans_le_prompt():
    from src.llm.prompts import build_system_prompt

    prompt = build_system_prompt(["shell_run"], "2026-09-01", "kaine")

    assert "━━ WHERE YOU ARE ━━" in prompt
    assert str(shell.get_cwd()) in prompt
