"""Recherche approfondie : décomposer, chercher en parallèle, combler, synthétiser.

Sous-graphe. `web_research_report` répond en un tour ; celui-ci découpe la
question, lance les recherches simultanément, regarde ce qui manque encore et
relance au plus `TOURS_MAX` fois.

Les appels au modèle sont injectés (`repondre`, `chercher`) : le graphe se teste
sans réseau ni LLM.
"""
from __future__ import annotations

import json
import operator
import re
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

#: Bornes. Une recherche approfondie coûte SOUS_QUESTIONS_MAX × TOURS_MAX
#: recherches ; sans plafond, une question vague vide un quota.
SOUS_QUESTIONS_MAX = 5
TOURS_MAX = 2


class Etat(TypedDict, total=False):
    question: str
    a_chercher: list[str]
    trouvailles: Annotated[list[dict], operator.add]
    tours: int
    rapport: str


def _liste_json(texte: str, limite: int) -> list[str]:
    """Les chaînes d'un tableau JSON dans une réponse, ou [] si illisible."""
    trouve = re.search(r"\[.*\]", texte or "", re.S)
    if not trouve:
        return []
    try:
        brut = json.loads(trouve.group(0))
    except (ValueError, TypeError):
        return []
    return [str(x).strip() for x in brut if str(x).strip()][:limite]


def construire(repondre: Callable[[str], str], chercher: Callable[[str], str]):
    """Le sous-graphe compilé. `repondre` interroge le modèle, `chercher` le web."""

    def decomposer(etat: Etat) -> dict:
        question = etat["question"]
        sortie = repondre(
            f"Découpe cette question en 2 à {SOUS_QUESTIONS_MAX} sous-questions "
            f"autonomes et complémentaires, chacune interrogeable seule sur le "
            f"web. Réponds UNIQUEMENT par un tableau JSON de chaînes.\n\n{question}")
        sous = _liste_json(sortie, SOUS_QUESTIONS_MAX)
        # Un découpage illisible ne doit pas tuer la recherche : on cherche la
        # question telle quelle.
        return {"a_chercher": sous or [question], "tours": 1}

    def eclater(etat: Etat):
        return [Send("chercher_une", {"sujet": s}) for s in etat.get("a_chercher", [])]

    def chercher_une(etat: dict) -> dict:
        sujet = etat["sujet"]
        try:
            contenu = chercher(sujet)
        except Exception as erreur:      # noqa: BLE001 — une source morte n'arrête rien
            contenu = f"[recherche échouée : {erreur}]"
        return {"trouvailles": [{"sujet": sujet, "contenu": contenu}]}

    def combler(etat: Etat) -> dict:
        """Ce qui manque encore, s'il reste un tour."""
        if etat.get("tours", 1) >= TOURS_MAX:
            return {"a_chercher": []}
        deja = "\n\n".join(f"## {t['sujet']}\n{t['contenu'][:1500]}"
                           for t in etat.get("trouvailles", []))
        sortie = repondre(
            f"Question initiale : {etat['question']}\n\n"
            f"Voici ce qui a été trouvé :\n{deja}\n\n"
            f"Quelles sous-questions restent SANS RÉPONSE et méritent une "
            f"recherche de plus ? Réponds UNIQUEMENT par un tableau JSON de "
            f"chaînes, vide s'il ne manque rien d'important.")
        return {"a_chercher": _liste_json(sortie, SOUS_QUESTIONS_MAX),
                "tours": etat.get("tours", 1) + 1}

    def encore(etat: Etat):
        # Rend des `Send` et non un nom de nœud : la relance doit ÉCLATER comme
        # le premier tour, sinon les sous-questions restantes partent en série.
        return eclater(etat) if etat.get("a_chercher") else "synthetiser"

    def synthetiser(etat: Etat) -> dict:
        sources = "\n\n".join(f"## {t['sujet']}\n{t['contenu']}"
                              for t in etat.get("trouvailles", []))
        rapport = repondre(
            f"Rédige une synthèse de la question suivante à partir des seules "
            f"informations ci-dessous. Cite les sources telles qu'elles "
            f"apparaissent. N'ajoute rien qui n'y figure pas ; si un point reste "
            f"sans réponse, dis-le.\n\nQuestion : {etat['question']}\n\n{sources}")
        return {"rapport": rapport}

    g = StateGraph(Etat)
    g.add_node("decomposer", decomposer)
    g.add_node("chercher_une", chercher_une)
    g.add_node("combler", combler)
    g.add_node("synthetiser", synthetiser)

    g.add_edge(START, "decomposer")
    g.add_conditional_edges("decomposer", eclater, ["chercher_une"])
    g.add_edge("chercher_une", "combler")
    # `eclater` est réutilisé pour la relance : le second tour part des mêmes
    # sujets, calculés par `combler`.
    g.add_conditional_edges("combler", encore, ["chercher_une", "synthetiser"])
    g.add_edge("synthetiser", END)
    return g.compile()
