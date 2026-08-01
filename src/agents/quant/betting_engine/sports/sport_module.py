"""`SportModule` — contrat dispatch d'un sport (feature builder + modèle).

Isolé dans son propre module SANS import, pour casser un cycle : `registry` construit
`SPORT_MODULES` en important les `live_models`, et les `live_models` ont besoin du seul
`SportModule`. S'ils l'importaient depuis `registry`, importer un live_model AVANT
`registry` déclencherait `registry` -> live_model (partiellement initialisé). En le
prenant ici, les live_models n'importent jamais `registry`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SportModule:
    sport: str
    build_feature_set: Callable        # (event, *, gateway, as_of) -> EventFeatureSet
    model: object                      # assess_data_readiness + predict_selections
