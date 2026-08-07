"""Primitives d'espérance — quatre fonctions pures, AUCUNE décision.

Ce module portait aussi `analyze_bet` et `analyze_parlay` : BET / WATCH /
ABSTAIN, `recommended_stake`, quart de Kelly. Une seconde pile de décision
complète, avec son propre dimensionnement, en parallèle de l'Advisor.

Elle était morte — aucun module du produit ne l'importait — mais rien ne le
disait, et sa signature en faisait une API d'apparence légitime, à un import
d'être vivante. La supprimer vaut mieux que la documenter : c'est précisément la
seconde pile que le reste du projet a passé son temps à fermer.

Ce qui reste ici ne décide rien. Le seuil, la comparaison et le dimensionnement
appartiennent à `betting_engine/value_engine/` et à l'Advisor.
"""

from __future__ import annotations

# Seuil provisoirement relevé à 6% : l'IC bootstrap du moteur ne capture que
# le bruit d'échantillonnage (pas l'erreur de spécification du modèle), donc
# la borne basse utilisée pour la décision est trop optimiste. À redescendre
# vers 4% une fois l'incertitude réelle calibrée au backtest.
EV_THRESHOLD = 0.06


def implied_probability(odds: float) -> float:
    """Probabilité implicite d'une cote, marge du book incluse."""
    return 1 / odds


def no_vig_probabilities(odds: dict[str, float | None]) -> dict[str, float]:
    """Retire la marge du book (normalisation proportionnelle) sur un marché complet.

    `odds` : ex. {"home": 2.15, "draw": 3.4, "away": 3.2} — les valeurs absentes
    (ex. pas de nul en tennis) sont ignorées.
    """
    raw = {selection: 1 / value for selection, value in odds.items() if value}
    total = sum(raw.values())
    return {selection: round(value / total, 4) for selection, value in raw.items()}


def expected_value(model_prob: float, odds: float) -> float:
    """EV d'un pari : (proba_modèle × cote) - 1. Positif = value."""
    return model_prob * odds - 1


def minimum_odds(model_prob: float) -> float:
    """Cote minimale pour que l'EV atteigne EV_THRESHOLD à cette probabilité."""
    return round((1 + EV_THRESHOLD) / model_prob, 3)


