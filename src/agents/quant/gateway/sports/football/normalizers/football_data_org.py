"""Normalizer football-data.org → faits canoniques football.

Déplacé depuis normalizers/football_data_org.py (v1). Déplacement pur : logique
inchangée, seuls les imports pointent vers sports/football/canonical_facts.
"""

from __future__ import annotations
from datetime import datetime

from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.normalizers.canonical_models import CanonicalPayload
from src.agents.quant.gateway.sports.football.canonical_facts import (
    CanonicalMatch,
    CanonicalStandingRow,
)


class FootballDataOrgNormalizer:
    def normalize_fixtures(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str, season: str
    ) -> CanonicalPayload:
        matches = []
        for match in raw.payload.get("matches", []):
            home_id, home_status = resolver.canonicalize("football_data_org", str(match["homeTeam"]["id"]), "team")
            away_id, away_status = resolver.canonicalize("football_data_org", str(match["awayTeam"]["id"]), "team")
            if home_status != "RESOLVED" or away_status != "RESOLVED":
                continue  # jamais de rattachement par proximité de nom — on écarte l'entrée
            full_time = match.get("score", {}).get("fullTime", {})
            matches.append(CanonicalMatch(
                canonical_match_id=f"football_data_org:{match['id']}",
                league_id=league_id,
                season=season,
                home_team_id=home_id,
                away_team_id=away_id,
                kickoff=datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00")),
                status=match["status"],
                goals_home=full_time.get("home"),
                goals_away=full_time.get("away"),
            ))
        return CanonicalPayload(kind="fixtures", matches=matches)

    def normalize_standings(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str
    ) -> CanonicalPayload:
        rows = []
        for group in raw.payload.get("standings", []):
            if group.get("type") != "TOTAL":
                continue
            for row in group.get("table", []):
                team_id, status = resolver.canonicalize("football_data_org", str(row["team"]["id"]), "team")
                if status != "RESOLVED":
                    continue
                rows.append(CanonicalStandingRow(
                    team_id=team_id, rank=row["position"], played=row["playedGames"], points=row["points"],
                ))
        return CanonicalPayload(kind="standings", standings=rows)
