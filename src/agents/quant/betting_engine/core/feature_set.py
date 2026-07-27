"""`EventFeatureSet` — contrat générique de features au niveau de l'événement (§6.2).

Générique et réutilisé tel quel par tous les sports (football, tennis,
baseball...) : les features ne sont pas portées par une entité isolée mais par
l'événement, découpées en trois niveaux qui évitent le principal piège — un
head-to-head n'appartient à aucun des deux participants, il n'existe que dans
leur relation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

FeatureValue = float | int | str | bool


@dataclass(frozen=True)
class EventFeatureSet:
    event_id: str
    sport: str
    as_of: datetime                        # cohérent avec available_to_model_time (gateway) —
                                           # aucune feature ne doit utiliser une donnée postérieure
    feature_set_version: str

    event_features: dict[str, FeatureValue]
    """Features de l'événement lui-même (surface, indoor, importance du tour,
    park factor...). Vide pour le football V0 : son signal est participant +
    matchup ; les features d'événement arriveront avec le context_schema."""

    participant_features: dict[str, dict[str, FeatureValue]]
    """{canonical_id du participant: ses features} — forme, force, ratings..."""

    matchup_features: dict[str, FeatureValue]
    """Features qui n'existent qu'en relation : head-to-head, différentiels."""

    missing_features: set[str]
    """Features attendues mais indisponibles — consommé par assess_data_readiness
    et remonté dans PredictionExplanation (§7). Peuplé, jamais interprété ici."""
