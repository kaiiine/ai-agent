"""Le corpus de l'agent de code doit rester lisible par son harnais.

Une entrée qui ne se parse pas disparaît SANS BRUIT du calcul. Vécu pendant
l'étiquetage : une ligne écrite `**attendu**:` au lieu de `attendu:` — du gras
markdown, réflexe normal — et l'étiquette était perdue sur 62.

Ces tests ne jugent pas les étiquettes, qui appartiennent à l'utilisateur. Ils
garantissent que le fichier reste exploitable et que l'espace d'étiquettes est
COMPLET : sept outils y manquaient au départ, dont les six du graphe de projet,
et une tâche « qu'est-ce qui casse si je change ça » n'avait alors aucune
réponse possible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))

from mesure_routage import _ENTREE, _HORS_GROUPES, etiquettes  # noqa: E402


@pytest.fixture(scope="module")
def entrees() -> list[tuple[str, str]]:
    return _ENTREE.findall((RACINE / "CORPUS-CODING.md").read_text(encoding="utf-8"))


def test_le_corpus_se_parse(entrees):
    cites = (RACINE / "CORPUS-CODING.md").read_text(encoding="utf-8").count("\n> ")

    assert len(entrees) == cites


def test_le_gras_markdown_est_tolere():
    """`**attendu**:` est ce qu'écrit quelqu'un qui remplit un markdown."""
    trouve = _ENTREE.findall("> une tâche\n\n**fait**: shell\n**attendu**: git, shell\n")

    assert trouve and etiquettes(trouve[0][1]) == ["git", "shell"]


def test_plusieurs_etiquettes_par_entree():
    """Une tâche demande souvent deux domaines — trouver le notebook, puis l'éditer."""
    assert etiquettes("notebook, filesystem") == ["notebook", "filesystem"]


def test_aucune_etiquette_hors_espace(entrees):
    """Une étiquette inconnue est une faute de frappe qui fausse le calcul en
    silence : `seb` pour `web` a survécu jusqu'à ce test."""
    from src.agents.coding.tool_retriever import _TOOL_GROUPS

    connues = (set(_TOOL_GROUPS) | set(_HORS_GROUPES.values())
               | {"blender", "playwright", "aucun", "ambigu"})
    posees = {e for _, brut in entrees for e in etiquettes(brut)}

    assert posees <= connues, sorted(posees - connues)


def test_lespace_couvre_tout_ce_qui_est_routable():
    """Sept outils natifs étaient routés sans domaine déclaré — donc invisibles
    dans la mesure et inétiquetables. Ce test les garde couverts."""
    from src.agents.coding.specialist import _get_coding_tools
    from src.agents.coding.tool_retriever import _ALWAYS_INCLUDED, _TOOL_GROUPS

    dans_un_groupe = {t for ts in _TOOL_GROUPS.values() for t in ts}
    # Les outils MCP portent leur serveur dans leur nom : ils ont un domaine sans
    # figurer dans `_TOOL_GROUPS`.
    orphelins = [o.name for o in _get_coding_tools()
                 if "__" not in o.name
                 and o.name not in dans_un_groupe
                 and o.name not in _ALWAYS_INCLUDED
                 and o.name not in _HORS_GROUPES]

    assert orphelins == []
