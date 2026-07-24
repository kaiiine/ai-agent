"""Contrat séparé pour les cotes — granularité différente des stats sportives
(bookmaker, mouvement de ligne, boosts). Jamais mélangé au même appel qu'un
SportsDataProvider (F7) : les cotes ne passent jamais par identity_resolver
ni par point_in_time_store, ce sont des données de marché en temps réel.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OddsQuote:
    match_id: str
    competition: str
    home_team: str
    away_team: str
    start_time: str | None
    status: str
    odds: dict  # {"home": float, "draw": float | None, "away": float}
    bookmaker: str
    fetched_at: str


class OddsProvider(Protocol):
    name: str

    def fetch_matches(self, sport: str, team: str = "") -> list[OddsQuote]:
        ...


class WinamaxOddsProvider:
    """Wrap du odds_fetcher.py existant. Un seul bookmaker en v1 — pas de
    comparaison multi-books (The Odds API resterait un ajout séparé si besoin)."""

    name = "winamax"

    def fetch_matches(self, sport: str = "football", team: str = "") -> list[OddsQuote]:
        from src.agents.quant.odds_fetcher import fetch_matches, find_match

        matches = fetch_matches(sport)
        if team:
            matches = find_match(matches, team)
        return [
            OddsQuote(
                match_id=m["match_id"],
                competition=m["competition"],
                home_team=m["home"],
                away_team=m["away"],
                start_time=m["start_time"],
                status=m["status"],
                odds=m["odds"],
                bookmaker=m["bookmaker"],
                fetched_at=m["fetched_at"],
            )
            for m in matches
        ]
