"""Cohérence du marché avant tout no-vig (aucun retrait de marge sur un
assemblage incomplet ou hétérogène).

Complétude STRUCTURELLE d'abord (l'ensemble exact des issues attendues), puis les
contrôles séparés — dont l'overround, distinct de la complétude. Toute violation
lève `MarketCoherenceError`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from src.agents.quant.betting_engine.core.errors import MarketCoherenceError
from src.agents.quant.betting_engine.core.market_model import MarketPrediction
from src.agents.quant.betting_engine.core.odds import OddsSnapshot

# Un scan Winamax unique produit un observed_at identique pour toutes les issues ;
# tolérance pour absorber des captures quasi-simultanées. Au-delà, cotes
# temporellement hétérogènes -> refus (jamais de mélange silencieux).
MAX_SNAPSHOT_SKEW = timedelta(minutes=2)

# Ensemble EXACT des issues attendues par market_type (complétude structurelle).
# Défaut football 1X2 ; un marché 2-way passe son propre ensemble via `expected_selections`
# (la sémantique vient du marché réel, jamais du nom du sport — PRD multisport §8).
_EXPECTED_SELECTIONS: dict[str, frozenset[str]] = {
    "MATCH_WINNER": frozenset({"home", "draw", "away"}),
}


def validate_market(
    market_odds: Sequence[OddsSnapshot],
    prediction: MarketPrediction,
    *,
    expected_selections: frozenset[str] | None = None,
) -> None:
    if not market_odds:
        raise MarketCoherenceError("marché vide")

    bookmakers = {o.bookmaker for o in market_odds}
    if len(bookmakers) != 1:
        raise MarketCoherenceError(f"bookmakers différents dans le marché : {bookmakers}")

    events = {o.event_id for o in market_odds}
    if len(events) != 1:
        raise MarketCoherenceError(f"événements différents dans le marché : {events}")

    market_types = {o.market_type for o in market_odds}
    if len(market_types) != 1:
        raise MarketCoherenceError(f"market_types différents dans le marché : {market_types}")
    market_type = next(iter(market_types))
    if prediction.market_type != market_type:
        raise MarketCoherenceError(
            f"prédiction ({prediction.market_type}) ≠ marché ({market_type})"
        )

    for o in market_odds:
        if o.decimal_odds <= 1.0:
            raise MarketCoherenceError(f"cote invalide (≤ 1) pour {o.selection} : {o.decimal_odds}")

    selections = [o.selection for o in market_odds]
    if len(selections) != len(set(selections)):
        raise MarketCoherenceError(f"sélections dupliquées : {selections}")

    # Complétude structurelle : l'ensemble EXACT des issues attendues. Le schéma du
    # marché (2-way/3-way) prime, sinon repli sur la table football par market_type.
    expected = expected_selections if expected_selections is not None else _EXPECTED_SELECTIONS.get(market_type)
    if expected is not None and set(selections) != expected:
        raise MarketCoherenceError(
            f"ensemble d'issues incomplet/inconnu pour {market_type} : "
            f"reçu {sorted(selections)}, attendu {sorted(expected)}"
        )

    if prediction.selection not in set(selections):
        raise MarketCoherenceError(
            f"sélection prédite {prediction.selection!r} absente du marché {sorted(selections)}"
        )

    times = [o.observed_at for o in market_odds]
    if max(times) - min(times) > MAX_SNAPSHOT_SKEW:
        raise MarketCoherenceError(
            f"snapshots temporellement incompatibles (skew > {MAX_SNAPSHOT_SKEW})"
        )

    # Overround : contrôle SÉPARÉ de la complétude. Un marché margé complet a une
    # somme d'implicites > 1 ; ≤ 1 = incohérent (incomplet malgré tout, ou arbitrage).
    overround = sum(1.0 / o.decimal_odds for o in market_odds)
    if overround <= 1.0:
        raise MarketCoherenceError(f"overround incohérent (Σ implicites = {overround:.4f} ≤ 1)")
