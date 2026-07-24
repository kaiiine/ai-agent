"""Provider football-data.org — couvre la saison en cours gratuitement (Ligue 1, Premier League...).

10 requêtes/minute, 12 compétitions majeures sur le tier gratuit. C'est le
provider prioritaire pour la saison en cours (voir provider_registry.FALLBACK_ORDER) —
API-Sports en tier gratuit ne couvre que 2022-2024.
"""

from __future__ import annotations
import os
from datetime import datetime, timezone

import requests

from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse, ProviderCapabilities

API_URL = "https://api.football-data.org/v4"
TIMEOUT = 5  # court : une cascade de fallback complète ne doit pas dépasser 2-3s perçues (PRD §7)
COVERED_SEASONS_FROM = 2021  # tier gratuit : saison en cours + quelques précédentes


def _api_key() -> str:
    key = os.environ.get("FOOTBALL_DATA_ORG_KEY", "")
    if not key:
        raise RuntimeError("FOOTBALL_DATA_ORG_KEY manquant dans .env")
    return key


class FootballDataOrgProvider:
    name = "football_data_org"
    supported_sports = ["football"]
    query_cost = 0.0

    def capabilities(self, sport: str) -> ProviderCapabilities:
        if sport != "football":
            return ProviderCapabilities()
        return ProviderCapabilities(fixtures=True, standings=True, recent_form=True, historical=True)

    def is_available(self, sport: str, season: str) -> bool:
        return sport == "football" and int(season) >= COVERED_SEASONS_FROM

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(
            f"{API_URL}/{path}", params=params or {},
            headers={"X-Auth-Token": _api_key()}, timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_league_fixtures(
        self, sport: str, provider_league_id: str, season: str,
        date_from: str | None = None, date_to: str | None = None,
    ) -> RawProviderResponse:
        params: dict = {"season": season}
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        data = self._get(f"competitions/{provider_league_id}/matches", params)
        return RawProviderResponse(
            payload=data,
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            request_metadata={"endpoint": "matches", "params": params, "competition": provider_league_id},
        )

    def fetch_standings(self, sport: str, provider_league_id: str, season: str) -> RawProviderResponse:
        data = self._get(f"competitions/{provider_league_id}/standings", {"season": season})
        return RawProviderResponse(
            payload=data,
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            request_metadata={"endpoint": "standings", "competition": provider_league_id},
        )

    def get_rate_limit_status(self) -> dict:
        return {"limit_per_minute": 10, "known_remaining": None}
