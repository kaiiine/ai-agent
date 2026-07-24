"""Normalizer API-Sports → modèle canonique."""

from __future__ import annotations
from datetime import datetime

from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.normalizers.canonical_models import (
    CanonicalPayload,
    CanonicalMatch,
    CanonicalStandingRow,
)



# API-Sports utilise des codes courts (FT, NS, PST...) — la gateway normalise vers
# un vocabulaire commun aux providers (celui de football-data.org : FINISHED,
# SCHEDULED, POSTPONED, CANCELLED...), sinon un filtre comme recent_form()
# écrirait un `if provider == ...` caché derrière une simple comparaison de statut.
_STATUS_MAP = {
    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
    "NS": "SCHEDULED", "TBD": "SCHEDULED",
    "PST": "POSTPONED", "CANC": "CANCELLED", "ABD": "CANCELLED",
}


def _canonical_status(short_code: str) -> str:
    return _STATUS_MAP.get(short_code, short_code)


class ApiSportsNormalizer:
    def normalize_fixtures(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str, season: str
    ) -> CanonicalPayload:
        matches = []
        for fixture in raw.payload.get("fixtures", []):
            home_id, home_status = resolver.canonicalize("api_sports", str(fixture["teams"]["home"]["id"]), "team")
            away_id, away_status = resolver.canonicalize("api_sports", str(fixture["teams"]["away"]["id"]), "team")
            if home_status != "RESOLVED" or away_status != "RESOLVED":
                continue  # jamais de rattachement par proximité de nom — on écarte l'entrée
            matches.append(CanonicalMatch(
                canonical_match_id=f"api_sports:{fixture['fixture']['id']}",
                league_id=league_id,
                season=season,
                home_team_id=home_id,
                away_team_id=away_id,
                kickoff=datetime.fromisoformat(fixture["fixture"]["date"]),
                status=_canonical_status(fixture["fixture"]["status"]["short"]),
                goals_home=fixture["goals"]["home"],
                goals_away=fixture["goals"]["away"],
            ))
        return CanonicalPayload(kind="fixtures", matches=matches)

    def normalize_standings(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str
    ) -> CanonicalPayload:
        data = raw.payload.get("standings", [])
        if not data:
            return CanonicalPayload(kind="standings", standings=[])

        rows = []
        for row in data[0]["league"]["standings"][0]:
            team_id, status = resolver.canonicalize("api_sports", str(row["team"]["id"]), "team")
            if status != "RESOLVED":
                continue
            rows.append(CanonicalStandingRow(
                team_id=team_id, rank=row["rank"], played=row["all"]["played"], points=row["points"],
            ))
        return CanonicalPayload(kind="standings", standings=rows)
