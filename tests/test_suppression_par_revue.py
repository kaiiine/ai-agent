"""Supprimer un fichier était impossible depuis l'agent de code.

Vécu, sur « supprime x.py » : rien ne se passe. Sa seule voie était `rm` via
`shell_run`, refusé comme destructif — et aucune confirmation ne peut être posée
depuis sa boucle, qui n'a pas de graphe. Aucun de ses quarante outils ne pouvait
effacer un fichier.

La revue de fichiers, elle, fonctionne déjà depuis le specialist : c'est elle qui
t'affiche le panneau et attend ton accord. Supprimer passe donc par le même
chemin qu'écrire, avec le même filet — un instantané est gardé avant.
"""
from __future__ import annotations

from pathlib import Path

from src.agents.coding.pending import appliquer, pending_changes, snapshots
from src.agents.coding.tools import propose_file_delete
from src.orchestrator.registry import build_all_tools
from src.ui.plan_mode import BLOCKED_TOOLS


def _proposer(chemin: Path) -> dict:
    pending_changes.clear()
    return propose_file_delete.invoke({"path": str(chemin)})


def test_une_suppression_passe_par_la_revue(tmp_path):
    cible = tmp_path / "x.py"
    cible.write_text("print(1)\n", encoding="utf-8")

    assert _proposer(cible)["status"] == "proposed"
    assert cible.exists(), "rien ne doit être effacé avant l'accord"

    change = pending_changes.pop_all()[0]
    assert change.supprime
    appliquer(change)
    assert not cible.exists()


def test_linstantane_est_pris_avant_deffacer(tmp_path):
    """Le même filet que pour une écriture : ce qui disparaît reste récupérable."""
    cible = tmp_path / "x.py"
    cible.write_text("contenu unique\n", encoding="utf-8")
    _proposer(cible)
    change = pending_changes.pop_all()[0]
    assert change.original == "contenu unique\n"
    appliquer(change)
    assert snapshots.restore(str(cible)) or Path(cible).read_text() == "contenu unique\n"


def test_un_fichier_absent_est_refuse_sans_proposition(tmp_path):
    reponse = _proposer(tmp_path / "jamais.py")
    assert reponse["status"] == "error"
    assert not pending_changes.pop_all()


def test_un_dossier_est_refuse(tmp_path):
    assert _proposer(tmp_path)["status"] == "error"


def test_loutil_est_enregistre_et_routable():
    from src.orchestrator.tool_retriever import TOOL_GROUPS

    assert "propose_file_delete" in {o.name for o in build_all_tools()}
    assert "propose_file_delete" in TOOL_GROUPS["filesystem"].tools


def test_le_mode_plan_le_bloque():
    """Il détruit : un plan ne l'exécute pas."""
    assert "propose_file_delete" in BLOCKED_TOOLS
