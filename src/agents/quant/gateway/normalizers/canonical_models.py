"""Modèles canoniques — mêmes champs, mêmes unités, quel que soit le provider d'origine."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CanonicalMatch:
    canonical_match_id: str
    league_id: str          # canonical_id de la ligue, ex. "league:ligue1"
    season: str
    home_team_id: str       # canonical_id, ex. "team:psg"
    away_team_id: str
    kickoff: datetime
    status: str              # "SCHEDULED" | "FINISHED" | "POSTPONED" | ...
    goals_home: int | None
    goals_away: int | None


@dataclass(frozen=True)
class CanonicalStandingRow:
    team_id: str
    rank: int
    played: int
    points: int


@dataclass(frozen=True)
class CanonicalPayload:
    """Sortie d'un normalizer — ce que la gateway enveloppe ensuite dans un DataEnvelope."""
    kind: str  # "fixtures" | "standings"
    matches: list[CanonicalMatch] = field(default_factory=list)
    standings: list[CanonicalStandingRow] = field(default_factory=list)
    event_time: datetime | None = None
    published_time: datetime | None = None


def match_to_dict(match: CanonicalMatch) -> dict:
    return {
        "canonical_match_id": match.canonical_match_id,
        "league_id": match.league_id,
        "season": match.season,
        "home_team_id": match.home_team_id,
        "away_team_id": match.away_team_id,
        "kickoff": match.kickoff.isoformat(),
        "status": match.status,
        "goals_home": match.goals_home,
        "goals_away": match.goals_away,
    }


def match_from_dict(data: dict) -> CanonicalMatch:
    return CanonicalMatch(
        canonical_match_id=data["canonical_match_id"],
        league_id=data["league_id"],
        season=data["season"],
        home_team_id=data["home_team_id"],
        away_team_id=data["away_team_id"],
        kickoff=datetime.fromisoformat(data["kickoff"]),
        status=data["status"],
        goals_home=data["goals_home"],
        goals_away=data["goals_away"],
    )


def standing_to_dict(row: CanonicalStandingRow) -> dict:
    return {"team_id": row.team_id, "rank": row.rank, "played": row.played, "points": row.points}


def standing_from_dict(data: dict) -> CanonicalStandingRow:
    return CanonicalStandingRow(team_id=data["team_id"], rank=data["rank"], played=data["played"], points=data["points"])


@dataclass(frozen=True)
class DataEnvelope:
    """Réponse finale servie à axon-quant — jamais un payload brut de provider."""
    payload: CanonicalPayload
    provider: str

    event_time: datetime | None
    published_time: datetime | None
    available_to_model_time: datetime
    fetched_at: datetime
    ingested_at: datetime

    data_quality: float
    freshness_score: float
    stale: bool = False
