"""Chargement de datasets RÉELS football-data.org -> list[CanonicalMatch].

Source : fixtures football-data.org enregistrées (`fl1_2025_matches.json`,
`sa_2025_matches.json`…), données réelles (mêmes payloads que les endpoints live,
provenance football_data_org). Chaque équipe est résolue en `canonical_id` via
l'identity_resolver de la gateway ; le `dataset_fingerprint` (sha256 du fichier
brut) ancre la reproductibilité.

Aucune donnée synthétique ici. Le chargeur est GÉNÉRIQUE (compétition-agnostique) :
onboarder une compétition = fournir sa fixture + son `league_id` canonique + saison
(mêmes IDs football_data_org, même walk-forward, aucune adaptation ad hoc — §6/§10).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch
from src.agents.quant.betting_engine.calibration.experiment_registry import dataset_fingerprint

_FIXTURES = Path(__file__).resolve().parents[5] / "tests" / "fixtures"

FL1_LEAGUE_ID = "competition:football:fra:ligue1"
FL1_SEASON = "2025"
DEFAULT_FL1_FIXTURE = _FIXTURES / "fl1_2025_matches.json"

SA_LEAGUE_ID = "competition:football:ita:serie_a"
SA_SEASON = "2025"
DEFAULT_SA_FIXTURE = _FIXTURES / "sa_2025_matches.json"

PD_LEAGUE_ID = "competition:football:esp:laliga"
PD_SEASON = "2025"
DEFAULT_PD_FIXTURE = _FIXTURES / "pd_2025_matches.json"

BL1_LEAGUE_ID = "competition:football:deu:bundesliga"
BL1_SEASON = "2025"
DEFAULT_BL1_FIXTURE = _FIXTURES / "bl1_2025_matches.json"

ELC_LEAGUE_ID = "competition:football:eng:championship"
ELC_SEASON = "2025"
DEFAULT_ELC_FIXTURE = _FIXTURES / "elc_2025_matches.json"

DED_LEAGUE_ID = "competition:football:nld:eredivisie"
DED_SEASON = "2025"
DEFAULT_DED_FIXTURE = _FIXTURES / "ded_2025_matches.json"

PPL_LEAGUE_ID = "competition:football:prt:primeira_liga"
PPL_SEASON = "2025"
DEFAULT_PPL_FIXTURE = _FIXTURES / "ppl_2025_matches.json"


def load_competition_season(
    resolver: IdentityResolver, path: Path, league_id: str, season: str,
):
    """GÉNÉRIQUE — `(matches, dataset_fingerprint, n_total_finished)`.

    Ne garde que les matchs FINISHED avec score ET dont les deux équipes résolvent
    en canonical_id (comptés dans `n_total_finished` mais écartés sinon : une équipe
    non résolue reste explicitement absente, jamais devinée)."""
    raw = path.read_bytes()
    data = json.loads(raw)

    matches: list[CanonicalMatch] = []
    n_finished = 0
    for m in data["matches"]:
        if m.get("status") != "FINISHED":
            continue
        full = m.get("score", {}).get("fullTime", {})
        gh, ga = full.get("home"), full.get("away")
        if gh is None or ga is None:
            continue
        n_finished += 1
        home_id, home_status = resolver.canonicalize("football_data_org", str(m["homeTeam"]["id"]), "team")
        away_id, away_status = resolver.canonicalize("football_data_org", str(m["awayTeam"]["id"]), "team")
        if home_status != "RESOLVED" or away_status != "RESOLVED":
            continue
        matches.append(CanonicalMatch(
            canonical_match_id=str(m["id"]),
            league_id=league_id,
            season=season,
            home_team_id=home_id,
            away_team_id=away_id,
            kickoff=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
            status="FINISHED",
            goals_home=int(gh),
            goals_away=int(ga),
        ))
    return matches, dataset_fingerprint(raw), n_finished


def load_fl1_2025(resolver: IdentityResolver, path: Path = DEFAULT_FL1_FIXTURE):
    """Ligue 1 2025-26 (wrapper du chargeur générique)."""
    return load_competition_season(resolver, path, FL1_LEAGUE_ID, FL1_SEASON)


def load_sa_2025(resolver: IdentityResolver, path: Path = DEFAULT_SA_FIXTURE):
    """Serie A 2025-26 (wrapper du chargeur générique) — onboardée le 2026-07-31."""
    return load_competition_season(resolver, path, SA_LEAGUE_ID, SA_SEASON)


def load_pd_2025(resolver: IdentityResolver, path: Path = DEFAULT_PD_FIXTURE):
    """LaLiga 2025-26 (wrapper du chargeur générique)."""
    return load_competition_season(resolver, path, PD_LEAGUE_ID, PD_SEASON)


def load_bl1_2025(resolver: IdentityResolver, path: Path = DEFAULT_BL1_FIXTURE):
    """Bundesliga (Allemagne) 2025-26 (wrapper du chargeur générique)."""
    return load_competition_season(resolver, path, BL1_LEAGUE_ID, BL1_SEASON)


def load_elc_2025(resolver: IdentityResolver, path: Path = DEFAULT_ELC_FIXTURE):
    """Championship anglaise 2025-26 (wrapper du chargeur générique)."""
    return load_competition_season(resolver, path, ELC_LEAGUE_ID, ELC_SEASON)


def load_ded_2025(resolver: IdentityResolver, path: Path = DEFAULT_DED_FIXTURE):
    """Eredivisie 2025-26 (wrapper du chargeur générique)."""
    return load_competition_season(resolver, path, DED_LEAGUE_ID, DED_SEASON)


def load_ppl_2025(resolver: IdentityResolver, path: Path = DEFAULT_PPL_FIXTURE):
    """Primeira Liga 2025-26 (wrapper du chargeur générique)."""
    return load_competition_season(resolver, path, PPL_LEAGUE_ID, PPL_SEASON)
