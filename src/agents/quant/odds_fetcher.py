"""Récupération des cotes Winamax (parsing du PRELOADED_STATE embarqué).

Pas d'API JSON publique : les données sont dans un <script> de la page HTML.
Les headers navigateur complets sont obligatoires (sinon Winamax sert un shell vide).
"""

from __future__ import annotations
import json
from datetime import datetime

import requests

BASE_URL = "https://www.winamax.fr/paris-sportifs/sports"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.8",
}
TIMEOUT = 20
STATE_MARKER = "var PRELOADED_STATE = "

SPORT_IDS = {
    "football": 1,
    "tennis": 2,
    "basketball": 3,
    "rugby": 5,
}


def _fetch_state(sport_id: int) -> dict:
    """Télécharge la page sport et extrait le JSON PRELOADED_STATE."""
    resp = requests.get(f"{BASE_URL}/{sport_id}", headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()

    html = resp.text
    start = html.find(STATE_MARKER)
    if start == -1:
        raise RuntimeError(
            "PRELOADED_STATE introuvable — Winamax a peut-être changé sa page "
            "ou servi une page anti-bot."
        )
    start += len(STATE_MARKER)
    state, _ = json.JSONDecoder().raw_decode(html[start:])
    return state


def fetch_matches(sport: str = "football") -> list[dict]:
    """Récupère les matchs à venir avec leurs cotes 1N2.

    Retourne une liste normalisée :
    [{match_id, competition, home, away, start_time, odds: {home, draw, away}, fetched_at}]
    """
    sport_id = SPORT_IDS.get(sport.lower())
    if sport_id is None:
        raise ValueError(f"Sport inconnu : {sport}. Choix : {list(SPORT_IDS)}")

    state = _fetch_state(sport_id)
    matches = state.get("matches", {})
    bets = state.get("bets", {})
    odds_map = state.get("odds", {})
    tournaments = state.get("tournaments", {})

    now = datetime.now().isoformat()
    results = []

    for match_id, match in matches.items():
        if match.get("sportId") != sport_id:
            continue

        bet = bets.get(str(match.get("mainBetId")), {})
        outcome_ids = bet.get("outcomes", [])
        odds_values = [odds_map.get(str(oid)) for oid in outcome_ids]
        if len(odds_values) < 2 or any(o is None for o in odds_values):
            continue

        tournament = tournaments.get(str(match.get("tournamentId")), {})

        home = match.get("competitor1Name") or ""
        away = match.get("competitor2Name") or ""
        if not home or not away:
            continue  # paris spéciaux (vainqueur tournoi…) sans deux équipes

        results.append({
            "match_id": str(match_id),
            "competition": tournament.get("tournamentName", ""),
            "home": home,
            "away": away,
            "start_time": datetime.fromtimestamp(match["matchStart"]).isoformat()
            if match.get("matchStart") else None,
            "status": match.get("status", ""),
            "odds": {
                "home": odds_values[0],
                "draw": odds_values[1] if len(odds_values) == 3 else None,
                "away": odds_values[-1],
            },
            "bookmaker": "winamax",
            "fetched_at": now,
        })

    return results


def find_match(matches: list[dict], team: str) -> list[dict]:
    """Filtre les matchs dont une équipe contient `team` (insensible à la casse)."""
    team_lower = team.lower()
    return [
        m for m in matches
        if team_lower in m["home"].lower() or team_lower in m["away"].lower()
    ]
