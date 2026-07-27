"""EV analytique — sur `fair_probability` uniquement.

Noyau importé de `quant/ev_engine.py` (transitoire). `EV_THRESHOLD` est une
POLITIQUE de décision (à externaliser en config versionnée à terme), pas une
constante mathématique intrinsèque au calcul d'EV.

En V0 (incertitude NOT_ESTIMATED), `probability_low`/`probability_high` ne sont
JAMAIS utilisés pour un EV prudent/optimiste : l'EV se calcule sur le point.
"""

from __future__ import annotations

from src.agents.quant.ev_engine import EV_THRESHOLD, expected_value, minimum_odds

__all__ = ["EV_THRESHOLD", "ev", "minimum_odds_for_value"]


def ev(model_probability: float, decimal_odds: float) -> float:
    """EV = model_probability × cote − 1."""
    return expected_value(model_probability, decimal_odds)


def minimum_odds_for_value(model_probability: float) -> float:
    """Cote minimale pour atteindre EV_THRESHOLD à cette probabilité (audit)."""
    return minimum_odds(model_probability)
