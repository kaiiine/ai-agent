"""Manifest football (§6.1) : ce que le sport déclare au reste du pipeline.

Déclare : la version du feature set, les features que `feature_engineering`
produit (et sur lesquelles un MarketModel peut compter), le contexte versionné,
les MarketModels enregistrés et leur **statut global codé en dur**.

Trois axes distincts, jamais mélangés :
  - Couverture : un modèle est-il enregistré pour ce (sport, market_type) ?
    Non -> `UNSUPPORTED` (BE-FR-007), sans code dédié pour le refuser.
  - Statut global du modèle : `EXPERIMENTAL` codé en dur ici — aucun chemin ne
    produit `SUPPORTED` (ni défaut, ni fallback, ni données parfaites). Le modèle
    plafonne aussi sa readiness runtime à EXPERIMENTAL (défense en profondeur).
  - Readiness par événement : calculée par `MarketModel.assess_data_readiness`,
    distincte des deux précédentes.
"""

from __future__ import annotations

from src.agents.quant.betting_engine.core.market_model import DataReadiness
from .market_models.one_x_two import OneXTwoModel

SPORT = "football"
FEATURE_SET_VERSION = "football-1.0"
CONTEXT_VERSION = "football-context-0"      # context_schema.py à venir (brique suivante)

# Features que feature_engineering produit et qu'un MarketModel peut requérir.
REQUIRED_PARTICIPANT_FEATURES = frozenset({
    "standings_strength",
    "form_points_per_game",
    "form_goal_diff_avg",
    "attack_strength",
    "defense_strength",
})
REQUIRED_MATCHUP_FEATURES = frozenset({
    "strength_differential",
})

# MarketModels enregistrés, par market_type.
REGISTERED_MARKET_MODELS: dict[str, object] = {
    "MATCH_WINNER": OneXTwoModel(),
}

# Statut GLOBAL de chaque modèle, codé en dur. EXPERIMENTAL tant qu'aucune
# calibration walk-forward documentée n'existe (aucune aujourd'hui) : jamais
# SUPPORTED. Déclaratif ici, ré-appliqué au runtime par le modèle lui-même.
GLOBAL_MODEL_STATUS: dict[str, DataReadiness] = {
    "MATCH_WINNER": DataReadiness.EXPERIMENTAL,
}


def is_market_supported(market_type: str) -> bool:
    """BE-FR-007 : un marché sans MarketModel enregistré est UNSUPPORTED.

    « supported » = *couvert par un modèle*, à ne pas confondre avec
    `DataReadiness.SUPPORTED` (statut de calibration, jamais atteint en V0)."""
    return market_type in REGISTERED_MARKET_MODELS
