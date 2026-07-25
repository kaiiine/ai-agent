"""Faits canoniques football (PRD v2 §5.3).

Ce que les providers affirment, normalisé au schéma football, sans transformation :
un match a eu lieu à telle date, tel score, tel statut ; une ligne de classement.
Stocké dans le point_in_time_store, versionné par schema_version="football/1.0".

Déplacé depuis normalizers/canonical_models.py (v1) — déplacement pur, aucune
modification de structure. canonical_models.py les ré-exporte pour transition.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CanonicalMatch:
    canonical_match_id: str
    league_id: str          # canonical_id de la ligue
    season: str
    home_team_id: str       # canonical_id
    away_team_id: str
    kickoff: datetime
    status: str             # "SCHEDULED" | "FINISHED" | "POSTPONED" | "CANCELLED"
    goals_home: int | None
    goals_away: int | None


@dataclass(frozen=True)
class CanonicalStandingRow:
    team_id: str
    rank: int
    played: int
    points: int


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
    return CanonicalStandingRow(
        team_id=data["team_id"], rank=data["rank"], played=data["played"], points=data["points"]
    )
