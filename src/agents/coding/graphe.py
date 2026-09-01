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


#: Construire coûte quelques secondes ; au-delà, le projet est trop gros pour
#: qu'un outil le fasse en silence au milieu d'une tâche.
_DELAI_CONSTRUCTION_S = 180

#: Ce qu'on compare au graphe. Les sources suivies par git, pas le disque entier :
#: `venv/`, `node_modules/` et `graphify-out/` bougent sans que le code change.
_DELAI_GIT_S = 5


def _derive(projet: Path, graphe: Path) -> str:
    """Ce que le graphe ne sait pas encore, en une phrase — ou rien.

    Le graphe vieillissait EN SILENCE. Vécu : celui de ce dépôt datait de cinq
    jours et annonçait `revision.py L78` pour une fonction passée ligne 162 ;
    l'agent citait des positions fausses sans que rien ne le signale, ni à lui ni
    à personne. Un graphe périmé est pire qu'absent — absent, on le sait.

    On compare la date du graphe à la plus récente des sources SUIVIES, ce qui
    couvre le cas qui nous a mordus : du travail non commité. Le résultat est
    consultatif : on ne refuse jamais de répondre, on dit ce qu'on sait.
    """
    try:
        p = subprocess.run(["git", "-C", str(projet), "ls-files"],
                           capture_output=True, text=True, timeout=_DELAI_GIT_S)
        if p.returncode != 0:
            return ""
        date_graphe = graphe.stat().st_mtime
        recents = 0
        for relatif in p.stdout.splitlines():
            fichier = projet / relatif
            try:
                if fichier.stat().st_mtime > date_graphe:
                    recents += 1
            except OSError:
                continue
    except Exception:                                        # noqa: BLE001
        return ""
    if not recents:
        return ""
    return (f"GRAPHE PÉRIMÉ : {recents} fichier(s) ont changé depuis sa "
            f"construction. Les chemins et numéros de ligne qu'il rend peuvent "
            f"avoir bougé — vérifie-les par une lecture avant de t'y fier, ou "
            f"demande `/graph {projet.name} --update` (sans appel de modèle).")


def _lancer(projet: Path, *args: str) -> Dict[str, Any]:
    """Exécute une commande graphify et rend sa sortie telle quelle.

    La sortie N'EST PAS reformatée : elle est déjà dense et bornée, et la
    retraiter ajouterait un endroit où la vérité peut diverger de l'outil.
    """
    graphe = _graphe_de(projet)
    if graphe is None:
        return {"status": "no_graph", "project": str(projet),
                "hint": f"Appelle graph_build(\"{projet.name}\") si la tâche demande de "
                        f"comprendre ce projet — 4 s, sans modèle. `/graph` est une "
                        f"commande de l'interface : tu ne peux pas la taper."}
    # `graphifyy` est une dépendance déclarée, installée dans le venv : on
    # l'appelle comme n'importe quel module. Le chemin `~/Documents/projets-perso/
    # graphify` était injecté en `PYTHONPATH` ici — un dossier voisin en dur, qui
    # marchait tant qu'il existait et qui masquait qu'une installation ordinaire
    # suffisait.
    try:
        p = subprocess.run(
            [sys.executable, "-m", "graphify", *args, "--graph", str(graphe)],
            capture_output=True, text=True, timeout=_DELAI_S,
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
    resultat: Dict[str, Any] = {"status": "ok", "result": sortie}
    perime = _derive(projet, graphe)
    if perime:
        resultat["stale"] = perime
    return resultat


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


@tool("graph_build")
def graph_build(project_path: str) -> Dict[str, Any]:
    """
    Construit le graphe de code d'un projet qui n'en a pas — 4 s, sans modèle.

    À faire quand `no_graph` te répond et que la tâche demande de COMPRENDRE le
    projet : ce qui appelle quoi, ce qu'un changement casserait, comment deux
    morceaux se relient. Mesuré sur 33 fichiers : 4 secondes, et « qui casse si
    je touche X » devient une réponse au lieu de quatre fichiers à lire.

    Inutile pour éditer un fichier qu'on te désigne : construire un graphe pour
    corriger une faute de frappe dépose un artefact que personne n'a demandé.

    Args:
        project_path: nom du projet, ou chemin
    """
    projet = _projet(project_path)
    if not projet.is_dir():
        return {"status": "error", "error": f"dossier introuvable : {projet}"}
    if _graphe_de(projet) is not None:
        # Déjà là : le rafraîchir est l'affaire de `update`, pas d'une
        # reconstruction — et surtout pas d'un silence qui laisserait croire
        # qu'on vient de bâtir ce qui existait déjà.
        return {"status": "ok", "message": "Le graphe existe déjà — interroge-le.",
                "project": str(projet)}

    # `--code-only` et `--no-label` DÉLIBÉRÉMENT : l'extraction sémantique de la
    # documentation et le nommage des communautés appellent un modèle, donc une
    # clé et un coût. Un outil que l'agent déclenche seul ne doit engager ni l'un
    # ni l'autre ; `/graph <projet>`, que l'utilisateur tape, le fait s'il le veut.
    for etapes in (("extract", str(projet), "--code-only"),
                   ("cluster-only", str(projet), "--no-viz", "--no-label")):
        try:
            p = subprocess.run([sys.executable, "-m", "graphify", *etapes],
                               capture_output=True, text=True, timeout=_DELAI_CONSTRUCTION_S)
        except subprocess.TimeoutExpired:
            return {"status": "error",
                    "error": f"graphify {etapes[0]} : délai dépassé "
                             f"({_DELAI_CONSTRUCTION_S}s) — projet trop gros, "
                             f"demande à l'utilisateur de lancer /graph."}
        except Exception as exc:                             # noqa: BLE001
            return {"status": "error", "error": str(exc)}
        if p.returncode != 0:
            return {"status": "error",
                    "error": (p.stderr or p.stdout or "")[-400:].strip()
                             or f"graphify {etapes[0]} : exit {p.returncode}"}

    if _graphe_de(projet) is None:
        return {"status": "error",
                "error": "graphify n'a rien écrit — poursuis sans le graphe."}
    return {"status": "ok", "project": str(projet),
            "message": "Graphe construit. Interroge-le : graph_explain, "
                       "graph_affected, graph_path."}


EXPORT_TOOLS = [graph_affected, graph_build, graph_explain, graph_path, graph_query]
