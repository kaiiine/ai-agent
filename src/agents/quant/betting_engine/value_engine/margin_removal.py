"""Retrait de marge (no-vig) — sur le marché COMPLET, jamais une cote isolée.

Le noyau (`no_vig_probabilities`, `implied_probability`) est importé de
`quant/ev_engine.py` (import transitoire, todo migration — jamais copié, source
unique gelée et testée). La cohérence/complétude du marché est vérifiée EN AMONT
par `market_coherence.validate_market` : ici on suppose l'assemblage déjà validé.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.agents.quant.ev_engine import implied_probability, no_vig_probabilities

from src.agents.quant.betting_engine.core.odds import OddsSnapshot


def implied_raw(odds: float) -> float:
    """Probabilité implicite brute d'une cote (marge du book incluse)."""
    return implied_probability(odds)


def no_vig(market_odds: Sequence[OddsSnapshot]) -> dict[str, float]:
    """Probabilités sans marge, par sélection, sur l'ensemble du marché."""
    return no_vig_probabilities({o.selection: o.decimal_odds for o in market_odds})
