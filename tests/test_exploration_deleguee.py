"""Fouiller un projet est le travail de l'agent de code, pas de l'orchestrateur.

Vécu, sur « analyse le projet ai-agent : qu'est-ce qui appelle la fonction
reviser ? » : l'orchestrateur a ouvert `local_find_file`, puis `local_grep`, puis
lu deux gros fichiers. 42 secondes, un grep en délai dépassé — pour une question
à laquelle `graph_explain reviser` répond en une seconde avec ses 22 connexions.
Le graphe, il ne l'a pas ; l'agent de code, si.

Il obéissait pourtant, et à QUATRE consignes convergentes :

  · « run_coding_agent is for tasks whose DELIVERABLE is source files » — une
    question ne livre pas de fichiers ;
  · « Task whose deliverable IS source files → run_coding_agent » — pareil ;
  · « ❌ NEVER delegate a task you can perform yourself with the tools already
    available » — et le catalogue rend TOUT disponible ;
  · « ❌ Do NOT use shell_cd / shell_ls / shell_pwd for code work » — qui nomme
    les outils shell, pas `local_grep`. Il a pris ceux qui restaient.

Les consignes sont réécrites. Mais une consigne se contourne — celles-là l'ont
été plusieurs fois cette session — alors la porte se ferme aussi.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.orchestrator import catalogue


@pytest.fixture(autouse=True)
def _catalogue_reel():
    from src.orchestrator.registry import build_all_tools

    catalogue.indexer(build_all_tools())
    yield
    catalogue.signaler_delegation(False)


def ouvrir(nom: str) -> str:
    return catalogue.obtenir_outil.invoke({"nom": nom})


# ── la porte ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("nom", sorted(catalogue._EXPLORATION))
def test_fouiller_un_projet_renvoie_vers_lagent_de_code(nom):
    catalogue.signaler_delegation(True)

    reponse = ouvrir(nom)

    assert "run_coding_agent" in reponse
    assert "graphe" in reponse


def test_lire_un_fichier_designe_reste_permis():
    """« Combien de lignes fait ~/rapport.md ? » sélectionne aussi l'agent de
    code — bloquer la lecture y serait absurde. La ligne juste sépare fouiller un
    projet de lire un fichier qu'on te montre."""
    catalogue.signaler_delegation(True)

    assert "disponible" in ouvrir("local_read_file")


def test_sans_tache_de_code_rien_nest_ferme():
    """« cherche le mot budget dans mes notes » ne sélectionne pas l'agent de
    code : la porte ne doit alors rien fermer du tout."""
    catalogue.signaler_delegation(False)

    for nom in catalogue._EXPLORATION:
        assert "disponible" in ouvrir(nom), nom


def test_le_drapeau_revient_a_faux():
    catalogue.signaler_delegation(True)
    catalogue.signaler_delegation(False)

    assert not catalogue.delegation_possible()


def test_un_nom_inconnu_reste_traite_comme_avant():
    catalogue.signaler_delegation(True)

    assert "ne figure pas au catalogue" in ouvrir("outil_qui_nexiste_pas")


# ── les consignes, rendues cohérentes ─────────────────────────────────────────
def _prompt() -> str:
    from src.llm.prompts import orchestrateur

    return Path(orchestrateur.__file__).read_text(encoding="utf-8")


def test_comprendre_du_code_est_aussi_le_travail_du_specialiste():
    """Le déclencheur était « deliverable IS source files » : une question sur
    un projet n'en livre aucun, donc rien ne se déclenchait."""
    source = _prompt()

    assert "UNDERSTANDING it" in source
    assert 'Task whose deliverable IS source files → run_coding_agent' not in source


def test_linterdit_dexploration_nomme_les_outils_de_lecture():
    """Il ne nommait que shell_cd / shell_ls / shell_pwd. Le modèle a pris
    local_find_file et local_grep, qui n'étaient pas cités."""
    source = _prompt()

    for nom in ("local_find_file", "local_grep", "local_read_file"):
        assert nom in source, nom


def test_le_refus_de_deleguer_ne_couvre_plus_le_code():
    """« NEVER delegate a task you can perform yourself with the tools already
    available » : avec le catalogue, tout est disponible — la règle avalait le
    cas qu'elle n'aurait jamais dû toucher."""
    source = _prompt()

    assert "NEVER delegate a task you can perform yourself" not in source
    assert "acting on something OTHER than a codebase" in source
