"""Provider API-Sports — wrap de l'existant (stats_aggregator) derrière le protocole gateway.

Le tier gratuit ne couvre que les saisons 2022-2024 (voir is_available) : sert
de fallback historique, pas de source pour la saison en cours (football-data.org
prend le relais pour ça).
"""

from __future__ import annotations
from datetime import datetime, timezone

from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse, ProviderCapabilities
from src.agents.quant.stats_aggregator import _api_get

FREE_TIER_SEASONS = {"2022", "2023", "2024"}


class ApiSportsProvider:
    name = "api_sports"
    supported_sports = ["football"]
    query_cost = 0.0  # gratuit sur le tier actuel

    def capabilities(self, sport: str) -> ProviderCapabilities:
        if sport != "football":
            return ProviderCapabilities()
        return ProviderCapabilities(fixtures=True, standings=True, recent_form=True, historical=True)

    def is_available(self, sport: str, season: str) -> bool:
        return sport == "football" and season in FREE_TIER_SEASONS

    def fetch_league_fixtures(
        self, sport: str, provider_league_id: str, season: str,
        date_from: str | None = None, date_to: str | None = None,
    ) -> RawProviderResponse:
        params = {"league": provider_league_id, "season": season}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        data = _api_get("fixtures", params)
        return RawProviderResponse(
            payload={"fixtures": data},
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            request_metadata={"endpoint": "fixtures", "params": params},
        )

    def fetch_standings(self, sport: str, provider_league_id: str, season: str) -> RawProviderResponse:
        params = {"league": provider_league_id, "season": season}
        data = _api_get("standings", params)
        return RawProviderResponse(
            payload={"standings": data},
            provider=self.name,
            fetched_at=datetime.now(timezone.utc),
            request_metadata={"endpoint": "standings", "params": params},
        )

    def get_rate_limit_status(self) -> dict:
        return {"limit_per_day": 100, "known_remaining": None}
