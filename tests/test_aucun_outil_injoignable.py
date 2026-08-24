"""Un outil qui existe mais que rien ne route est du code mort qui se croit vivant.

Vécu : `create_slides` était écrit, testé, documenté dans le README — et importé
NULLE PART. Le paquet `src/agents/slides/` entier (rendu HTML, rendu PPTX,
outil) était donc mort du point de vue de l'agent. Une demande de présentation
ne pouvait qu'atterrir sur l'API Google Slides, qui construit une diapositive
PAR APPEL et épuise le budget de tours avant la fin du deck.

Rien ne signalait la panne : les tests du renderer passaient, le README le
décrivait, et le seul symptôme était que l'agent « choisissait mal ».

Ces deux tests ferment les deux moitiés du chemin :
  décoré `@tool` → enregistré       (sinon l'agent ne le voit jamais)
  enregistré     → routé ou épinglé (sinon il n'entre dans aucune sélection)
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_AGENTS = _RACINE / "src" / "agents"

#: Outils volontairement hors registre, avec la raison. Tout ajout ici doit
#: être un CHOIX écrit, pas un oubli qui passe.
_HORS_REGISTRE: dict[str, str] = {
    # Génération d'images par Stable Diffusion local. `diffusers` et `torch` sont
    # installés, mais le dossier de modèle de `IMAGE_SETTINGS` n'existe pas :
    # enregistrer ces outils mettrait dans le prompt deux actions qui échouent à
    # l'appel. À réactiver le jour où un modèle est téléchargé.
    "generate_fantasy_image": "modèle Stable Diffusion local absent",
    "generate_realistic_image": "modèle Stable Diffusion local absent",
}


def _outils_declares() -> dict[str, Path]:
    """Tout ce que `@tool("nom")` définit sous src/agents/, par lecture de l'AST.

    L'AST plutôt qu'un import : un module qui échoue à l'import disparaîtrait
    silencieusement du décompte, ce qui est précisément la panne à détecter.
    """
    trouves: dict[str, Path] = {}
    for fichier in _AGENTS.rglob("*.py"):
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in noeud.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                cible = deco.func
                nom_deco = getattr(cible, "id", None) or getattr(cible, "attr", None)
                if nom_deco != "tool":
                    continue
                if deco.args and isinstance(deco.args[0], ast.Constant):
                    trouves[str(deco.args[0].value)] = fichier
                else:
                    trouves[noeud.name] = fichier
    return trouves


@pytest.fixture(scope="module")
def enregistres() -> set[str]:
    """Les outils de l'ORCHESTRATEUR."""
    from src.orchestrator.registry import build_all_tools
    return {t.name for t in build_all_tools()}


@pytest.fixture(scope="module")
def joignables(enregistres) -> set[str]:
    """Orchestrateur ET specialist : il y a deux registres, et un outil servi
    par le second (`propose_file_change`, `dev_plan_create`, `notebook_*`…) est
    bien vivant même s'il ne figure pas dans le premier."""
    from src.agents.coding.specialist import _get_coding_tools
    return enregistres | {t.name for t in _get_coding_tools()}


def test_le_scanner_trouve_bien_des_outils():
    """Un scanner cassé rendrait les deux tests suivants vides et donc verts."""
    declares = _outils_declares()
    assert len(declares) > 40, f"scanner suspect : {len(declares)} outils trouvés"


def test_tout_outil_declare_est_enregistre(joignables):
    declares = _outils_declares()
    manquants = {
        nom: str(chemin.relative_to(_RACINE))
        for nom, chemin in declares.items()
        if nom not in joignables and nom not in _HORS_REGISTRE
    }
    assert not manquants, (
        "outils décorés `@tool` absents des DEUX registres — aucun agent ne les "
        "verra jamais :\n  " + "\n  ".join(f"{n}  ({c})" for n, c in sorted(manquants.items())))


def test_tout_outil_enregistre_est_joignable(enregistres):
    """Enregistré ne suffit pas : la sélection se fait par GROUPE."""
    from src.orchestrator.tool_retriever import TOOL_GROUPS, _PINNED_TOOLS

    routables = {t for g in TOOL_GROUPS.values() for t in g.tools} | set(_PINNED_TOOLS)
    orphelins = sorted(enregistres - routables)
    assert not orphelins, (
        "outils enregistrés mais dans aucun groupe ni épinglés — ils n'entreront "
        f"dans aucune sélection : {orphelins}")


def test_aucun_groupe_ne_cite_un_outil_inexistant(enregistres):
    """La faute symétrique : un groupe qui promet un outil supprimé."""
    from src.orchestrator.tool_retriever import TOOL_GROUPS

    fantomes = sorted(
        {t for g in TOOL_GROUPS.values() for t in g.tools} - enregistres)
    assert not fantomes, f"groupes citant des outils inexistants : {fantomes}"


def test_le_deck_local_est_le_chemin_par_defaut():
    """L'invariant produit derrière tout ça : « fais-moi une présentation » doit
    mener au générateur local, qui rend le deck ENTIER en un appel — pas à
    l'API Google Slides, qui en rend une diapositive par appel."""
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import ToolRetriever

    retriever = ToolRetriever(build_all_tools())
    for requete in ("fais-moi une présentation sur TypeScript",
                    "fais un deck pour la réunion de lundi",
                    "prépare un powerpoint sur le projet"):
        outils = {t.name for t in retriever.get(requete)}
        assert "create_slides" in outils, f"deck local absent pour « {requete} »"
