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
    entities: Callable | None = None   # () -> Sequence[CanonicalEntity] du sport
    # (RawBookmakerEvent) -> (competition_id, statut, méthode). None = résolution
    # par `raw_tournament_id`, valable pour les sports de LIGUE dont le tid est
    # stable d'une saison à l'autre. Le tennis ne peut pas s'en servir : son tid
    # identifie une ÉDITION de tournoi et change chaque semaine.
    resolve_competition: Callable | None = None

    def known_entities(self):
        """Entités canoniques de CE sport, pour la résolution d'identité.

        Chaque sport a son propre espace de noms — un joueur de tennis et un club
        de football ne se croisent jamais. Sans cette couture, la résolution par
        défaut retombait sur le référentiel FOOTBALL quel que soit le sport
        demandé : les six autres sports étaient enregistrés, atteignables, et
        échouaient tous en IDENTITY_UNRESOLVED avant même d'atteindre leur modèle.
        """
        return tuple(self.entities()) if self.entities is not None else ()
