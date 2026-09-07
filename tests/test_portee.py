"""La colonne `projet` — la portée d'une leçon, écrite au moment où elle naît.

Elle ne se rattrape pas après coup : `decisions.jsonl` ne la portait pas avant
cette branche, donc l'information n'existerait nulle part à reconstruire. D'où
des tests sur l'écriture elle-même, et pas seulement sur la relecture.
"""
from __future__ import annotations

import json

from src.infra import trace


def _lignes(fichier) -> list[dict]:
    return [json.loads(l) for l in fichier.read_text(encoding="utf-8").splitlines() if l]


def test_chaque_ligne_porte_le_projet(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "_projet_courant", lambda: "axon")
    trace.nouveau_run("tui")
    fichier = tmp_path / "d.jsonl"
    trace.inscrire(trace.Action(genre=trace.RATTRAPAGE, outil="x"), fichier=fichier)
    assert _lignes(fichier)[0]["projet"] == "axon"


def test_le_projet_est_resolu_a_chaque_run_pas_une_fois_par_processus(
        tmp_path, monkeypatch):
    """L'agent shell déplace le `cwd` en cours de session.

    Une valeur figée à l'import étiquetterait tous les tours suivants du nom du
    premier projet ouvert — et toutes les leçons apprises ensuite seraient
    attribuées au mauvais dépôt.
    """
    fichier = tmp_path / "d.jsonl"
    monkeypatch.setattr(trace, "_projet_courant", lambda: "premier")
    trace.nouveau_run()
    trace.inscrire(trace.Action(genre=trace.ROUTE), fichier=fichier)

    monkeypatch.setattr(trace, "_projet_courant", lambda: "second")
    trace.nouveau_run()
    trace.inscrire(trace.Action(genre=trace.ROUTE), fichier=fichier)

    assert [l["projet"] for l in _lignes(fichier)] == ["premier", "second"]


def test_hors_depot_le_projet_est_nomme_pas_vide(tmp_path, monkeypatch):
    """Un vide se confondrait à la relecture avec « colonne pas encore écrite »,
    et la portée d'une leçon ne doit jamais se deviner.

    `tmp_path` de pytest n'a aucun `.git` au-dessus de lui — c'est ce qui rend
    la branche atteignable sans truquer la remontée d'arborescence.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr("src.agents.shell.tools.get_cwd", raising=False)
    assert trace._projet_courant() == trace.HORS_REPO


def test_le_projet_courant_rend_le_nom_du_depot(tmp_path, monkeypatch):
    depot = tmp_path / "mon-projet"
    (depot / ".git").mkdir(parents=True)
    monkeypatch.chdir(depot)
    monkeypatch.delattr("src.agents.shell.tools.get_cwd", raising=False)
    assert trace._projet_courant() == "mon-projet"


def test_un_sous_repertoire_rend_le_depot_pas_le_sous_repertoire(
        tmp_path, monkeypatch):
    """La portée est le DÉPÔT. Un compte par sous-répertoire éparpillerait la
    même leçon sur autant de lignes qu'il y a de dossiers."""
    depot = tmp_path / "mon-projet"
    (depot / ".git").mkdir(parents=True)
    profond = depot / "src" / "infra"
    profond.mkdir(parents=True)
    monkeypatch.chdir(profond)
    monkeypatch.delattr("src.agents.shell.tools.get_cwd", raising=False)
    assert trace._projet_courant() == "mon-projet"


def test_une_resolution_qui_echoue_ne_casse_pas_le_run(monkeypatch):
    """Même règle que tout le module : la trace ne casse jamais ce qu'elle
    observe. Un `cwd` supprimé sous les pieds ne doit pas emporter le tour."""
    def _explose():
        raise OSError("cwd disparu")

    monkeypatch.setattr(trace.Path, "cwd", staticmethod(_explose))
    monkeypatch.delattr("src.agents.shell.tools.get_cwd", raising=False)
    assert trace.nouveau_run()          # un identifiant est bien rendu
