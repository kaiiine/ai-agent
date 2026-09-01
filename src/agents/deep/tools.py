"""L'outil qui expose la recherche approfondie."""
from __future__ import annotations

from langchain_core.tools import tool

from src.agents.deep.graphe import SOUS_QUESTIONS_MAX, TOURS_MAX, construire


def _modele():
    from src.infra.settings import settings
    from src.llm.models import (
        make_llm_gemini,
        make_llm_mistral,
        make_llm_nvidia,
        make_llm_ollama_cloud,
    )

    from src.llm.backends import fabriques as _registre

    fabriques = _registre()
    return fabriques.get(settings.llm_backend, make_llm_ollama_cloud)()


def _texte(contenu) -> str:
    """Le contenu d'un message, que le modèle réponde en chaîne ou en blocs."""
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in contenu)
    return str(contenu)


def repondre_avec_modele():
    """La fonction d'appel au modèle, prête pour le sous-graphe."""
    return _repondre(_modele())


def chercher_web(sujet: str) -> str:
    from src.agents.search.tools import web_research_report

    return web_research_report.invoke({"query": sujet, "max_results": 6})


def _repondre(llm):
    def appeler(prompt: str) -> str:
        return _texte(llm.invoke(prompt).content)
    return appeler


def _chercher(sujet: str) -> str:
    from src.agents.search.tools import web_research_report

    return web_research_report.invoke({"query": sujet, "max_results": 6})


@tool("deep_research")
def deep_research(question: str) -> str:
    """Recherche APPROFONDIE : découpe la question, cherche en parallèle, synthétise.

    Utilise ce tool quand l'utilisateur veut :
    - une recherche poussée, complète, détaillée sur un sujet
    - un dossier, un état de l'art, un comparatif argumenté
    - creuser une question qui demande plusieurs angles

    Mots-clés : recherche approfondie, dossier, creuse, état de l'art, complet,
    détaillé, compare en profondeur, analyse poussée, fais le tour de

    Différence avec web_research_report : celui-ci fait UNE recherche et répond.
    `deep_research` en lance plusieurs en parallèle, regarde ce qui manque, et
    relance un tour. Il coûte donc plusieurs fois plus cher et prend plus de
    temps — pour une question factuelle simple, prendre web_research_report.

    La recherche est lancée par AXON dès que tu appelles ce tool ; son résultat
    t'arrive ensuite. N'annonce rien avant de l'avoir reçu.

    Args:
        question: la question à creuser, formulée entièrement
    """
    import json

    from src.agents.deep.noeud import MARQUEUR

    if not question.strip():
        return json.dumps({"status": "error", "error": "Question vide."})
    return json.dumps({"status": MARQUEUR, "question": question.strip()},
                      ensure_ascii=False)
