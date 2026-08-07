"""Vérification de couverture par appel réel (PRD v2 §7.3, GW-FR-005).

L'activation d'une couverture exige `verification_method="live_call"` : la
documentation d'un provider ne suffit pas. Cette procédure effectue un appel
réel, constate le résultat, et écrit l'entrée horodatée dans le coverage registry.

`data_type` → endpoint provider :
  STANDINGS            -> fetch_standings
  FIXTURES / RESULTS   -> fetch_league_fixtures (une réponse mixte couvre les deux)
"""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

from src.agents.quant.gateway.core.provider_registry import REGISTRY
from src.agents.quant.gateway.registries.provider_coverage_registry import (
    CoverageStatus,
    ProviderCompetitionCoverage,
    record_coverage,
)


def _raw_is_non_empty(raw_payload: dict, data_type: str) -> bool:
    if data_type == "STANDINGS":
        standings = raw_payload.get("standings", [])
        return bool(standings)
    # FIXTURES / RESULTS
    return bool(raw_payload.get("matches") or raw_payload.get("fixtures"))


def verify(
    provider_name: str,
    competition_id: str,
    provider_competition_id: str,
    season: str,
    data_type: str,
    sport: str,
    db_path: Path | None = None,
) -> ProviderCompetitionCoverage:
    """Effectue l'appel réel et enregistre le résultat (live_call).

    FULL si le provider répond avec des données non vides, ABSENT sinon
    (indisponible, saison bloquée, réponse vide). Toujours horodaté.
    """
    provider = REGISTRY[provider_name].provider
    verified_at = datetime.now(timezone.utc)

    status = CoverageStatus.ABSENT
    if provider.is_available(sport, season):
        try:
            if data_type == "STANDINGS":
                raw = provider.fetch_standings(sport, provider_competition_id, season)
            else:
                raw = provider.fetch_league_fixtures(sport, provider_competition_id, season)
            if _raw_is_non_empty(raw.payload, data_type):
                status = CoverageStatus.FULL
        except Exception:
            status = CoverageStatus.ABSENT

    entry = ProviderCompetitionCoverage(
        provider=provider_name,
        competition_id=competition_id,
        provider_competition_id=provider_competition_id,
        season=season,
        data_type=data_type,
        status=status,
        verified_at=verified_at,
        verification_method="live_call",
    )
    record_coverage(entry, db_path)
    return entry
