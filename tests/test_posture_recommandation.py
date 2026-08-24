"""La posture est EXTRAITE, jamais choisie par le modèle après coup.

Une préférence exprimée en français doit se lire toujours de la même façon.
Laisser le LLM arbitrer à chaque tour entre « le plus sûr » et « le plus
rentable », c'est accepter que la même phrase donne deux réponses différentes
selon le backend, l'humeur du modèle et la longueur du contexte.

Le cas qui décide de la conception est « je veux du sûr mais que ça rapporte » :
les deux vocabulaires y sont présents, et la sûreté doit l'emporter. Un
utilisateur qui demande les deux demande d'abord de ne pas perdre.
"""
from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.markets.review_ranking import (
    RecommendationPosture,
)
from src.agents.quant.conversation.posture import detecter_posture


@pytest.mark.parametrize("phrase", [
    "je veux quelque chose de sûr",
    "donne-moi des paris prudents",
    "les plus fiables",
    "ceux qui ont le plus de chances de passer",
    "quasi sûr de passer",
    "le plus probable",
    "un risque faible",
    "je préfère que ça passe",
])
def test_une_demande_de_securite_donne_safety_first(phrase):
    assert detecter_posture(phrase) is RecommendationPosture.SAFETY_FIRST


@pytest.mark.parametrize("phrase", [
    "je veux la meilleure value",
    "donne-moi les value bets du jour",
    "le meilleur rendement",
    "le meilleur edge",
    "la meilleure EV",
    "les plus rentables",
    "je prends plus de risque pour gagner plus",
])
def test_une_demande_explicite_de_valeur_donne_value_first(phrase):
    assert detecter_posture(phrase) is RecommendationPosture.VALUE_FIRST


@pytest.mark.parametrize("phrase", [
    "je veux du sûr mais que ça rapporte",
    "des paris sûrs avec le meilleur rendement",
    "le plus probable et le plus rentable",
])
def test_en_cas_de_conflit_la_securite_prime(phrase):
    """L'exigence explicite du cahier : la valeur ne fait que départager."""
    assert detecter_posture(phrase) is RecommendationPosture.SAFETY_FIRST


@pytest.mark.parametrize("phrase", [
    "",
    None,
    "j'aimerais faire des paris sportifs, des combinés de préférence",
    "tu me conseillerais quoi ce soir ?",
])
def test_sans_demande_la_posture_reste_protectrice(phrase):
    """Ne rien demander ne doit pas exposer au risque."""
    assert detecter_posture(phrase) is RecommendationPosture.SAFETY_FIRST


def test_la_detection_ne_depend_d_aucun_modele():
    """Le test qui donne sa valeur aux autres : la réponse est la même sur une
    machine sans LLM, sans réseau et sans embedder."""
    import inspect

    from src.agents.quant.conversation import posture

    source = inspect.getsource(posture)
    for dependance in ("llm", "invoke", "embed", "similarity", "requests.", "openai"):
        assert dependance not in source.lower()


def test_la_posture_voyage_jusqu_a_la_requete_d_allocation():
    """Point 8 : le jour où un modèle devient SUPPORTED, le chemin de la MISE
    doit pouvoir lire ce que l'utilisateur a demandé. Sans ce champ, une demande
    « je veux du sûr » retomberait silencieusement sur « la meilleure espérance
    d'abord »."""
    import dataclasses

    from src.agents.quant.advisor.domain.requests import RecommendationRequest

    champs = {f.name: f for f in dataclasses.fields(RecommendationRequest)}
    assert "posture" in champs
    assert champs["posture"].default == "SAFETY_FIRST", (
        "le défaut de l'allocateur doit être protecteur, comme celui de la revue")


def test_la_revue_accepte_la_posture_de_bout_en_bout():
    """Elle doit traverser toute la chaîne, sinon elle est décorative."""
    import inspect

    from src.agents.quant.conversation import market_review, recommend

    assert "posture" in inspect.signature(market_review.construire_review).parameters
    assert "posture" in inspect.signature(
        market_review.construire_review_depuis).parameters
    assert "posture" in inspect.signature(recommend._construire_review).parameters
