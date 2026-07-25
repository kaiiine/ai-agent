"""Module sportif football — implémente le contrat SportModule (PRD v2 §6).

Regroupe : schéma canonique versionné (football/1.0), normalizers par provider,
validateur de payload, types d'entités, calculateurs dérivés. Enregistré dans
sports/registry.py.
"""

from __future__ import annotations

from src.agents.quant.gateway.canonical.data_types import DataType
from src.agents.quant.gateway.normalizers.canonical_models import CanonicalPayload
from src.agents.quant.gateway.sports.errors import PayloadValidationError
from src.agents.quant.gateway.sports.football import derived
from src.agents.quant.gateway.sports.football.normalizers.api_sports import ApiSportsNormalizer
from src.agents.quant.gateway.sports.football.normalizers.football_data_org import FootballDataOrgNormalizer

SCHEMA_VERSION = "football/1.0"


class FootballModule:
    sport = "football"
    schema_version = SCHEMA_VERSION

    def supported_data_types(self) -> set[str]:
        return {DataType.FIXTURES, DataType.RESULTS, DataType.STANDINGS}

    def normalizers(self) -> dict[str, object]:
        return {
            "api_sports": ApiSportsNormalizer(),
            "football_data_org": FootballDataOrgNormalizer(),
        }

    def validate_payload(self, payload: object, data_type: str) -> None:
        if not isinstance(payload, CanonicalPayload):
            raise PayloadValidationError(
                f"football: payload attendu CanonicalPayload, reçu {type(payload).__name__}"
            )
        # Cohérence minimale fait ↔ type de donnée.
        if data_type in (DataType.FIXTURES, DataType.RESULTS) and payload.standings:
            raise PayloadValidationError(f"football: un payload {data_type} ne doit pas porter de standings")
        if data_type == DataType.STANDINGS and payload.matches:
            raise PayloadValidationError("football: un payload STANDINGS ne doit pas porter de matches")

    def entity_types(self) -> set[str]:
        return {"team"}

    def derived_calculators(self) -> dict[str, object]:
        return dict(derived.CALCULATORS)

    def is_schema_compatible(self, stored_schema_version: str) -> bool:
        # v2 : granularité par sport, égalité stricte (§14.4). À affiner si un
        # jour un data_type évolue plus vite que les autres.
        return stored_schema_version == self.schema_version
