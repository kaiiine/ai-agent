"""Manifest football (§6.1) : ce que le sport déclare au reste du pipeline.

En V0 : la version du feature set, les features que `feature_engineering`
s'engage à produire (donc sur lesquelles un futur MarketModel pourra compter), le
contexte versionné — et AUCUN market_model encore enregistré. Conséquence directe
de BE-FR-007 : sans MarketModel pour un `(sport, market_type)`, ce marché est
`UNSUPPORTED` par défaut, sans code dédié pour le refuser.
"""

from __future__ import annotations

SPORT = "football"
FEATURE_SET_VERSION = "football-1.0"
CONTEXT_VERSION = "football-context-0"      # context_schema.py à venir (brique suivante)

# Features que feature_engineering produit et qu'un MarketModel peut requérir.
REQUIRED_PARTICIPANT_FEATURES = frozenset({
    "standings_strength",
    "form_points_per_game",
    "form_goal_diff_avg",
})
REQUIRED_MATCHUP_FEATURES = frozenset({
    "strength_differential",
})

# Aucun MarketModel enregistré encore (one_x_two viendra à l'étape MarketModel,
# avec la migration Dixon-Coles). Tout market_type est donc UNSUPPORTED.
REGISTERED_MARKET_MODELS: dict[str, object] = {}


def is_market_supported(market_type: str) -> bool:
    """BE-FR-007 : un marché sans MarketModel enregistré est UNSUPPORTED."""
    return market_type in REGISTERED_MARKET_MODELS
