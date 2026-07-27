"""Registre des modules sportifs (§6.1) — dispatch sport -> (feature builder, modèle).

Minimal, pas un framework de plugins : un seul sport enregistré (football).
L'orchestrateur racine dispatche via ce registre — aucun `"football"` codé en
dur ailleurs. Ajouter un sport = enregistrer un `SportModule` ici.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .football.feature_engineering import build_event_feature_set
from .football.market_models.one_x_two import OneXTwoModel


@dataclass(frozen=True)
class SportModule:
    sport: str
    build_feature_set: Callable        # (event, *, gateway, as_of) -> EventFeatureSet
    model: object                      # assess_data_readiness + predict_selections


SPORT_MODULES: dict[str, SportModule] = {
    "football": SportModule("football", build_event_feature_set, OneXTwoModel()),
}
