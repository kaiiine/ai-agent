"""Contrats génériques du Market Model (§7) — neutres, un modèle par (sport, market_type).

`MarketModel` produit des **probabilités de marché** et rien d'autre : pas d'EV,
pas de comparaison aux cotes, pas de sizing, pas de décision (ça, c'est le
`value_engine`). `predict` prend `point_in_time` obligatoire (ADR-004).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from .canonical_event import CanonicalEvent, CanonicalMarket
from .feature_set import EventFeatureSet


class DataReadiness(str, Enum):
    SUPPORTED = "SUPPORTED"                # jamais atteint tant qu'aucune calibration walk-forward
    EXPERIMENTAL = "EXPERIMENTAL"          # modèle en place, non calibré — plafond actuel
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # données requises absentes pour CET événement
    UNSUPPORTED = "UNSUPPORTED"            # aucun modèle pour ce (sport, market_type)


class UncertaintyStatus(str, Enum):
    """Statut EXPLICITE de l'incertitude — évite qu'un intervalle absent soit lu
    comme un intervalle nul. `NOT_ESTIMATED` = pas d'intervalle probabiliste
    fondé à ce stade (le contrat impose deux nombres non-null, cf. PRD §7 ; on
    répète alors `fair_probability`, jamais comme un intervalle réel)."""

    NOT_ESTIMATED = "NOT_ESTIMATED"
    ESTIMATED = "ESTIMATED"


@dataclass(frozen=True)
class PredictionExplanation:
    """Pourquoi ce modèle a produit cette probabilité (ADR-013). Non optionnel."""

    top_features: list[tuple[str, float]]   # quantités RÉELLES du modèle + valeurs (pas des importances)
    missing_features: set[str]
    warnings: list[str]
    confidence_drivers: list[str]


@dataclass(frozen=True)
class MarketPrediction:
    sport: str
    market_type: str
    selection: str
    fair_probability: float
    probability_low: float                  # cf. uncertainty_status : NOT_ESTIMATED => = fair_probability
    probability_high: float
    uncertainty_status: UncertaintyStatus
    model_version: str
    data_quality: float
    calibration_status: DataReadiness
    point_in_time: datetime                 # propagé dans les métadonnées (ADR-004)
    explanation: PredictionExplanation


@runtime_checkable
class MarketModel(Protocol):
    sport: str
    market_type: str                        # un seul market_type par implémentation
    model_version: str

    def required_features(self) -> set[str]: ...

    def assess_data_readiness(
        self, event: CanonicalEvent, features: EventFeatureSet
    ) -> DataReadiness: ...

    def predict(
        self,
        event: CanonicalEvent,
        market: CanonicalMarket,
        features: EventFeatureSet,
        point_in_time: datetime,
    ) -> MarketPrediction: ...
