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
from src.agents.quant.betting_engine.support_status import resolve_market_status
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

# Statut GLOBAL de chaque modèle, DÉRIVÉ du ledger de support (support_status.py),
# plus un littéral codé en dur : `SUPPORTED` exige un `ModelSupportDecision`
# persisté par le verdict mécanique de maturity.py. Aucune preuve persistée à ce
# jour -> EXPERIMENTAL (sans I/O : ledger absent). Même source de vérité que le
# plafond de readiness runtime du modèle -> aucune divergence possible.
GLOBAL_MODEL_STATUS: dict[str, DataReadiness] = {
    market_type: resolve_market_status(model.model_name, model.model_version)
    for market_type, model in REGISTERED_MARKET_MODELS.items()
}


def is_market_supported(market_type: str) -> bool:
    """BE-FR-007 : un marché sans MarketModel enregistré est UNSUPPORTED.

    « supported » = *couvert par un modèle*, à ne pas confondre avec
    `DataReadiness.SUPPORTED` (statut de calibration, jamais atteint en V0)."""
    return market_type in REGISTERED_MARKET_MODELS
