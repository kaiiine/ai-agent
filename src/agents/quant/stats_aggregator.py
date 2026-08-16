"""Stats sportives via API-Football, avec cache SQLite local."""

from __future__ import annotations
import json
import os
import sqlite3
import time
import unicodedata
from pathlib import Path

import requests

API_URL = "https://v3.football.api-sports.io"
CACHE_DB = Path.home() / ".axon" / "quant_cache.db"
CACHE_TTL = 6 * 3600  # 6h — les stats d'avant-match ne bougent pas toutes les minutes
TIMEOUT = 15

_SUFFIXES = {"fc", "cf", "sc", "afc", "cfc"}
_ALT_MARKERS = {
    "ii", "iii", "b", "reserve", "reserves", "youth", "academy",
    "u17", "u18", "u19", "u20", "u21", "u23",
    "w", "women", "woman", "fem", "femenino", "feminine",
}


def _normalize(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_name.lower().split())


def _strip_suffix(name: str) -> str:
    words = name.split()
    if len(words) > 1 and words[-1].lower().rstrip(".") in _SUFFIXES:
        return " ".join(words[:-1])
    return name


def _is_alt_team(name: str) -> bool:
    return any(w in _ALT_MARKERS for w in _normalize(name).split())


def _api_key() -> str:
    key = os.environ.get("API_FOOTBALL_KEY", "")
    if not key:
        raise RuntimeError("API_FOOTBALL_KEY manquant dans .env")
    return key


def _db() -> sqlite3.Connection:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, ts REAL)"
    )
    return conn


def _cache_get(key: str) -> dict | list | None:
    conn = _db()
    try:
        row = conn.execute("SELECT value, ts FROM cache WHERE key = ?", (key,)).fetchone()
        if row and (time.time() - row[1]) < CACHE_TTL:
            return json.loads(row[0])
        return None
    finally:
        conn.close()


def _cache_set(key: str, value: dict | list) -> None:
    conn = _db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, ts) VALUES (?, ?, ?)",
            (key, json.dumps(value), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def _api_get(endpoint: str, params: dict, base_url: str = API_URL) -> list:
    """Appel api-sports mis en cache.

    `base_url` est paramétrable parce que les six produits api-sports sont six
    HÔTES distincts derrière la MÊME clé. La clé de cache le porte : sans lui,
    `games:{"league":1,...}` du baseball et du football américain se répondraient
    l'un pour l'autre.
    """
    cache_key = f"{base_url}|{endpoint}:{json.dumps(params, sort_keys=True)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    resp = requests.get(
        f"{base_url}/{endpoint}",
        params=params,
        headers={"x-apisports-key": _api_key()},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json().get("response", [])
    _cache_set(cache_key, data)
    return data


def search_team(name: str) -> dict | None:
    """Trouve une équipe par nom, tolérant accents et suffixes (FC/CF)."""
    without_suffix = _strip_suffix(name)
    target = _normalize(without_suffix)

    variants = [name, without_suffix, _normalize(name), target]
    variants = list(dict.fromkeys(variants))  # dédoublonne sans perdre l'ordre

    candidates: dict[int, dict] = {}
    for variant in variants:
        if not variant:
            continue
        results = _api_get("teams", {"search": variant}) or []
        for result in results:
            team = result["team"]
            candidates[team["id"]] = team
        if candidates:
            break  # une variante a trouvé quelque chose, pas besoin d'essayer les autres

    if not candidates:
        return None

    def score(team: dict) -> tuple:
        exact_match = _normalize(team["name"]) != target
        alt_team = _is_alt_team(team["name"])
        return (exact_match, alt_team, len(team["name"]))

    best = min(
        candidates.values(),
        key=score,
    )
    return {"id": best["id"], "name": best["name"], "country": best.get("country", "")}


def recent_form(team_id: int, last: int = 10) -> list[dict]:
    """Les N derniers matchs d'une équipe.

    Retourne [{date, home, away, goals_home, goals_away, is_home, result,
    opponent_id, league_id, season}] du plus récent au plus ancien.
    result : "W" | "D" | "L" du point de vue de l'équipe.
    """
    fixtures = _api_get("fixtures", {"team": team_id, "last": last})
    results = []
    for f in fixtures:
        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]
        goals_home = f["goals"]["home"]
        goals_away = f["goals"]["away"]
        if goals_home is None or goals_away is None:
            continue
        is_home = home_id == team_id
        team_goals = goals_home if is_home else goals_away
        opp_goals = goals_away if is_home else goals_home
        result = "W" if team_goals > opp_goals else "L" if team_goals < opp_goals else "D"
        results.append({
            "date": f["fixture"]["date"][:10],
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
            "goals_home": goals_home,
            "goals_away": goals_away,
            "is_home": is_home,
            "result": result,
            "opponent_id": away_id if is_home else home_id,
            "league_id": f["league"]["id"],
            "season": f["league"]["season"],
        })
    return results


def standings_strength(league_id: int, season: int) -> dict[int, float]:
    """Proxy de force par équipe depuis le classement d'une ligue.

    Interpolation linéaire : 1er → 1.3, dernier → 0.7, milieu → 1.0.
    Proxy grossier mais suffisant pour pondérer la qualité des adversaires
    dans l'estimation de forme. Retourne {team_id: force}.

    ⚠ LEAKAGE — l'API ne fournit que le classement ACTUEL de la saison
    (pas de paramètre date). Acceptable en usage live (contamination légère :
    le classement du jour inclut les matchs de la forme eux-mêmes).
    INTERDIT en backtest tel quel : le classement doit y être reconstruit
    depuis les fixtures antérieures à chaque date simulée, sinon le backtest
    utilise de l'information du futur et ses résultats sont invalides.
    """
    data = _api_get("standings", {"league": league_id, "season": season})
    if not data:
        return {}

    table = data[0]["league"]["standings"][0]
    n = len(table)
    if n < 2:
        return {}

    ratings = {}
    for row in table:
        rank = row["rank"]
        # rank 1 → 1.3, rank n → 0.7
        ratings[row["team"]["id"]] = round(1.3 - 0.6 * (rank - 1) / (n - 1), 3)
    return ratings


def opponent_ratings_for_form(form: list[dict]) -> dict[int, float]:
    """Construit le dict {opponent_id: force} pour une forme donnée.

    Utilise le classement de la ligue la plus fréquente dans la forme.
    Retourne {} si les standings sont indisponibles — le moteur fonctionne
    alors sans ajustement adversaire (dégradation propre).
    """
    if not form:
        return {}
    leagues: dict[tuple[int, int], int] = {}
    for match in form:
        key = (match.get("league_id"), match.get("season"))
        if key[0] is not None:
            leagues[key] = leagues.get(key, 0) + 1
    if not leagues:
        return {}
    league_id, season = max(leagues, key=leagues.get)
    try:
        return standings_strength(league_id, season)
    except Exception:
        return {}


