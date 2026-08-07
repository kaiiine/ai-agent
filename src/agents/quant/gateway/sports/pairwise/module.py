"""Module sportif générique pour les sports à deux équipes (PRD v2 §6).

Basket, baseball, football américain, hockey et volley partagent le contrat
`SportModule` sans rien qui les distingue à ce niveau : même schéma canonique
(deux équipes, un score, un statut), même provider, même type d'entité. Cinq
classes auraient été cinq copies — et la seule différence réelle, l'espace
d'identités du produit api-sports, est déjà portée par le normalizer.

Aucun calculateur dérivé n'est déclaré : la forme récente et la force au
classement sont des notions football, calculées par `sports/football/derived.py`.
Les modèles de ces cinq sports n'en consomment aucune — ils tiennent leurs notes
Elo de leur propre dataset embarqué. Déclarer un calculateur vide serait affirmer
une capacité inexistante.
"""

from __future__ import annotations

from src.agents.quant.gateway.canonical.data_types import DataType
from src.agents.quant.gateway.normalizers.canonical_models import CanonicalPayload
from src.agents.quant.gateway.sports.errors import PayloadValidationError
from src.agents.quant.gateway.sports.pairwise.normalizer import (
    NAMESPACES,
    ApiSportsPairwiseNormalizer,
)


class PairwiseSportModule:
    """Un sport à deux équipes, servi par api-sports."""

    def __init__(self, sport: str, schema_version: str | None = None) -> None:
        if sport not in NAMESPACES:
            raise ValueError(f"sport pairwise inconnu : {sport!r}")
        self.sport = sport
        self.schema_version = schema_version or f"{sport}/1.0"

    def supported_data_types(self) -> set[str]:
        # Ni STANDINGS : non sondé chez ce provider hors football, et déclaré
        # `standings=False` dans ses capacités.
        return {DataType.FIXTURES, DataType.RESULTS}

    def normalizers(self) -> dict[str, object]:
        return {"api_sports": ApiSportsPairwiseNormalizer(self.sport)}

    def validate_payload(self, payload: object, data_type: str) -> None:
        if not isinstance(payload, CanonicalPayload):
            raise PayloadValidationError(
                f"{self.sport}: payload attendu CanonicalPayload, "
                f"reçu {type(payload).__name__}")
        if payload.standings:
            raise PayloadValidationError(
                f"{self.sport}: aucun payload de ce sport ne porte de standings")

    def entity_types(self) -> set[str]:
        return {"team"}

    def derived_calculators(self) -> dict[str, object]:
        return {}

    def is_schema_compatible(self, stored_schema_version: str) -> bool:
        return stored_schema_version == self.schema_version


PAIRWISE_MODULES: dict[str, PairwiseSportModule] = {
    sport: PairwiseSportModule(sport) for sport in sorted(NAMESPACES)
}
