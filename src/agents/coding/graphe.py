"""Interroger le graphe du projet, plutôt que de le lire.

Graphify construit `graphify-out/graph.json` puis se REQUÊTE — c'est son modèle,
et son README le dit sans détour : « preferring scoped queries like
`graphify query "<question>"` over reading the full report ».

Axon faisait l'inverse. Le prompt du specialist ordonnait de lire
`GRAPH_REPORT.md` en premier ; mesuré sur ce dépôt, le fichier fait 147 Ko et
passe JUSTE sous le plafond de 200 Ko de `local_read_file` — il partait donc
entier, 42 733 tokens, la moitié du budget d'un tour. Il prétendait « remplacer
la lecture de 10-20 fichiers », qui en coûtent 13 000 à 15 000.

Les quatre commandes ci-dessous existaient déjà dans graphify et n'étaient pas
utilisées :

    path      36 tk    chemin le plus court entre deux symboles
    affected 150 tk    traversée INVERSE — qui casse si je touche X
    explain  330 tk    définition, source, voisins, degré
    query   ≤2000 tk   traversée large, plafond en tokens réglable

Toutes tournent en ~1,5 s, en traversée locale, SANS appel modèle. `affected`
répond exactement à ce que le prompt réclamait jusque-là via `local_grep` :
« cherche tous les appelants avant de toucher la fonction ».
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

#: Graphify n'est pas installé dans l'environnement d'Axon : on le lance avec
#: son dépôt en `PYTHONPATH`, exactement comme la commande `/graph`.
_DEPOT = Path.home() / "Documents" / "projets-perso" / "graphify"

#: Au-delà, la commande est en défaut, pas lente : le graphe se traverse en
#: mémoire et les mesures tiennent sous deux secondes.
_DELAI_S = 60

#: Le plafond par défaut de `query` côté graphify. Répété ici pour que la
#: docstring de l'outil l'annonce au modèle sans avoir à le deviner.
_BUDGET_DEFAUT = 2000


def _projet(chemin: str) -> Path:
    """Résout un chemin de projet — absolu, relatif au shell, ou nom de projet.

    `.` seul ne suffit pas : le cwd du shell d'Axon vaut souvent `$HOME`, et la
    résolution rendait alors `no_graph` sur un projet qui a pourtant son graphe.
    """
    p = Path(chemin or ".").expanduser()
    if p.is_absolute():
        return p
    try:
        from src.agents.shell.tools import get_cwd
        candidat = Path(get_cwd()) / p
        if (candidat / "graphify-out").is_dir():
            return candidat
    except Exception:                                        # noqa: BLE001
        pass
    try:
        from src.utils.paths import get_projects_dir
        candidat = get_projects_dir() / chemin
        if candidat.is_dir():
            return candidat
    except Exception:                                        # noqa: BLE001
        pass
    return Path.cwd() / p if not p.is_absolute() else p


def _graphe_de(projet: Path) -> Path | None:
    for candidat in (projet / "graphify-out" / "graph.json", projet / "graph.json"):
        if candidat.exists():
            return candidat
    return None


def _lancer(projet: Path, *args: str) -> Dict[str, Any]:
    """Exécute une commande graphify et rend sa sortie telle quelle.

    La sortie N'EST PAS reformatée : elle est déjà dense et bornée, et la
    retraiter ajouterait un endroit où la vérité peut diverger de l'outil.
    """
    graphe = _graphe_de(projet)
    if graphe is None:
        return {"status": "no_graph", "project": str(projet),
                "hint": f"Lance /graph {projet.name} depuis Axon — sous-processus, zéro token."}
    env = {**os.environ, "PYTHONPATH": str(_DEPOT)}
    try:
        p = subprocess.run(
            [sys.executable, "-m", "graphify", *args, "--graph", str(graphe)],
            env=env, capture_output=True, text=True, timeout=_DELAI_S,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"graphify {args[0]} : délai dépassé ({_DELAI_S}s)"}
    except Exception as exc:                                 # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    if p.returncode != 0:
        return {"status": "error",
                "error": (p.stderr or p.stdout or "")[-400:].strip() or f"exit {p.returncode}"}
    sortie = (p.stdout or "").strip()
    if not sortie:
        return {"status": "not_found", "query": " ".join(args)}
    return {"status": "ok", "result": sortie}


# ── Les quatre outils ─────────────────────────────────────────────────────────
#
# Un outil par question, plutôt qu'un outil générique à paramètre `mode` : le
# modèle choisit sur la description, et quatre descriptions courtes se
# distinguent mieux qu'une longue à embranchements.

from langchain_core.tools import tool                        # noqa: E402
from pydantic import BaseModel, Field                        # noqa: E402

#: Chaque argument porte sa description DANS le schéma, pas seulement dans la
#: docstring. LangChain ne remonte pas la section « Args: » en descriptions de
#: champs : sans ces modèles, le modèle voyait `budget: integer` sans savoir
#: qu'il s'agit de tokens. C'est le même défaut que celui corrigé sur
#: `ask_clarification`, et il se reproduit à chaque outil écrit sans schéma.

_CHEMIN = Field(description="Nom du projet (ex « axon-landing ») ou chemin, "
                            "absolu ou relatif au shell.")


class ArgsAffected(BaseModel):
    project_path: str = _CHEMIN
    symbol: str = Field(description="Nom exact du symbole, parenthèses comprises "
                                    "— ex « build_system_prompt() ».")
    depth: int = Field(default=2, description="Profondeur de remontée dans les appelants.")


class ArgsExplain(BaseModel):
    project_path: str = _CHEMIN
    symbol: str = Field(description="Nom exact du symbole — ex « ToolRetriever ».")


class ArgsPath(BaseModel):
    project_path: str = _CHEMIN
    source: str = Field(description="Symbole de départ.")
    target: str = Field(description="Symbole d'arrivée.")


class ArgsQuery(BaseModel):
    project_path: str = _CHEMIN
    question: str = Field(description="La question, en langue naturelle.")
    budget: int = Field(default=_BUDGET_DEFAUT,
                        description="Plafond de la réponse EN TOKENS. 2000 par "
                                    "défaut ; baisse-le pour un simple ordre de grandeur.")


@tool("graph_affected", args_schema=ArgsAffected)
def graph_affected(project_path: str, symbol: str, depth: int = 2) -> Dict[str, Any]:
    """
    Qui casse si je modifie ce symbole — traversée INVERSE du graphe du projet.

    À appeler AVANT toute édition d'une fonction partagée : la liste des
    appelants décide si le correctif va dans la fonction elle-même ou chez
    chacun d'eux. Remplace un local_grep sur tout le dépôt, en ~150 tokens.

    Args:
        project_path: nom du projet, ou chemin (absolu ou relatif au shell)
        symbol: nom exact du symbole, parenthèses comprises — ex "build_system_prompt()"
        depth: profondeur de remontée (défaut 2)
    Returns:
        {"status": "ok", "result": "..."} · {"status": "no_graph"} si pas de graphe
    """
    return _lancer(_projet(project_path), "affected", symbol, "--depth", str(depth))


@tool("graph_explain", args_schema=ArgsExplain)
def graph_explain(project_path: str, symbol: str) -> Dict[str, Any]:
    """
    Ce qu'est un symbole et ce qui l'entoure : source, ligne, voisins, degré.

    Le premier réflexe devant un nom inconnu — moins cher qu'ouvrir le fichier,
    et il donne en plus les liens que la lecture seule ne montre pas (~330 tokens).

    Args:
        project_path: nom du projet, ou chemin
        symbol: nom exact du symbole — ex "ToolRetriever" ou "build_system_prompt()"
    """
    return _lancer(_projet(project_path), "explain", symbol)


@tool("graph_path", args_schema=ArgsPath)
def graph_path(project_path: str, source: str, target: str) -> Dict[str, Any]:
    """
    Comment deux symboles sont reliés — chemin le plus court, avec le type de
    chaque lien et son niveau de confiance (EXTRACTED / INFERRED).

    Répond à « est-ce que A dépend vraiment de B, et par où ? » en ~36 tokens.

    Args:
        project_path: nom du projet, ou chemin
        source: symbole de départ
        target: symbole d'arrivée
    """
    return _lancer(_projet(project_path), "path", source, target)


@tool("graph_query", args_schema=ArgsQuery)
def graph_query(project_path: str, question: str, budget: int = _BUDGET_DEFAUT) -> Dict[str, Any]:
    """
    Question large sur l'architecture — traversée du graphe, sortie plafonnée.

    À réserver aux questions qu'aucun symbole précis ne résume ("qu'est-ce qui
    relie l'authentification à la base ?"). Pour un symbole connu, préfère
    graph_explain ou graph_affected : dix fois moins cher et plus précis.

    Args:
        project_path: nom du projet, ou chemin
        question: la question, en langue naturelle
        budget: plafond de la réponse EN TOKENS (défaut 2000) — baisse-le si tu
                veux seulement l'ordre de grandeur
    """
    return _lancer(_projet(project_path), "query", question, "--budget", str(budget))


EXPORT_TOOLS = [graph_affected, graph_explain, graph_path, graph_query]
