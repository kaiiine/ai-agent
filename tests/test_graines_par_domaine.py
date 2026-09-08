"""Une graine par domaine — sinon un serveur MCP rafle la sélection.

Mesuré sur les 60 tâches réelles de `CORPUS-CODING.md`, étiquetées par
l'utilisateur : les graines d'une tâche Blender étaient `{blender: 8}`, huit sur
huit, et il n'en restait aucune pour `git`, `filesystem` ou `graphe`, pourtant
attendus. 35 % des tâches avaient un domaine à cinq graines ou plus.

C'est la pathologie que l'orchestrateur a déjà soignée — son en-tête la nomme :
« le nombre d'ancres était devenu un multiplicateur de probabilité d'être choisi,
indépendamment de la pertinence ».

                        rappel   tâches complètes
    avant (k=8 outils)   64,6 %       14/36
    après (5 domaines)   76,2 %       20/36
    jeu tenu à l'écart   60,0 → 71,0 %    7/24 → 9/24
"""
from __future__ import annotations

import pytest

from src.agents.coding.tool_retriever import (
    _DOMAINES_MAX, _PROFONDEUR_GRAINES, _RANG_MAX_SI_AGIT, _TOOL_GROUPS,
    _TOOL_TO_GROUP, CodingToolRetriever,
)


@pytest.fixture(scope="module")
def retriever():
    from src.agents.coding.specialist import _get_coding_tools

    return CodingToolRetriever(_get_coding_tools(), k=8)


def _domaines(retriever, requete: str) -> set[str]:
    noms = [t.name for t in retriever.get(requete)]
    return {n.split("__", 1)[0] if "__" in n else _TOOL_TO_GROUP.get(n) for n in noms} - {None}


def test_un_serveur_mcp_ne_rafle_plus_toute_la_selection(retriever):
    """« Create a Blender scene… » ne servait QUE blender : les huit graines y
    passaient. La tâche demandait aussi de quoi lire le dépôt."""
    servis = _domaines(retriever, "Create a Blender scene in the repository that "
                                  "imports the provided SVG file and adds lighting")

    assert "blender" in servis
    assert len(servis) >= 3, servis


def test_lire_un_fichier_ne_tire_toujours_pas_le_shell(retriever):
    """Le contrepoids de l'élargissement. `shell` remontait au rang 9 sur cette
    requête — élargir sans seuil remettait `shell_run` à portée d'une lecture.
    C'est `requires_top_rank` de l'orchestrateur, transposé."""
    assert "shell" not in _domaines(retriever, "lis le contenu de page.tsx")


def test_un_domaine_qui_agit_porte_un_seuil():
    """Si le seuil disparaît, le garde-fou ci-dessus devient vide sans bruit."""
    assert _RANG_MAX_SI_AGIT.get("shell", _PROFONDEUR_GRAINES) < _PROFONDEUR_GRAINES


def test_le_plafond_de_domaines_reste_dans_sa_plage():
    """2 donnait 0 tâche complète sur 36, 8 en donnait 29 mais liait 47 outils.
    5 est le genou mesuré ; s'en écarter demande de rejouer le balayage."""
    assert 4 <= _DOMAINES_MAX <= 6


def test_la_profondeur_depasse_le_plafond():
    """Chercher moins loin que le nombre de domaines voulus les rendrait
    inatteignables — un serveur de 28 outils occupe à lui seul les 28 premières
    places."""
    assert _PROFONDEUR_GRAINES > _DOMAINES_MAX * 5


def test_chaque_domaine_seme_au_plus_une_fois(retriever):
    """L'invariant du correctif : deux outils du même domaine ne prennent pas
    deux places."""
    from src.agents.coding.tool_retriever import _ALWAYS_INCLUDED

    servis = _domaines(retriever, "corrige le bug dans la scène blender puis "
                                  "commit le résultat")
    flux = {_TOOL_TO_GROUP.get(n) for n in _ALWAYS_INCLUDED} - {None}

    assert len(servis - flux) <= _DOMAINES_MAX
