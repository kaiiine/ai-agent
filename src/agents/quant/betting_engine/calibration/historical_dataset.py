"""Chargement du dataset RÉEL (Ligue 1 2025-26) -> list[CanonicalMatch].

Source : la fixture football-data.org enregistrée (`fl1_2025_matches.json`),
donnée réelle (mêmes matchs que les golden tests de la gateway). Chaque équipe
est résolue en `canonical_id` via l'identity_resolver de la gateway ; le
`dataset_fingerprint` (sha256 du fichier brut) ancre la reproductibilité.

Aucune donnée synthétique ici : ce chargeur alimente le PREMIER run officiel.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch
from src.agents.quant.betting_engine.calibration.experiment_registry import dataset_fingerprint

FL1_LEAGUE_ID = "competition:football:fra:ligue1"
FL1_SEASON = "2025"
DEFAULT_FL1_FIXTURE = (
    Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "fl1_2025_matches.json"
)


def load_fl1_2025(resolver: IdentityResolver, path: Path = DEFAULT_FL1_FIXTURE):
    """`(matches: list[CanonicalMatch], dataset_fingerprint, n_total_finished)`.

    Ne garde que les matchs FINISHED avec score ET dont les deux équipes résolvent
    en canonical_id (comptés à part sinon).
    """
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
            league_id=FL1_LEAGUE_ID,
            season=FL1_SEASON,
            home_team_id=home_id,
            away_team_id=away_id,
            kickoff=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
            status="FINISHED",
            goals_home=int(gh),
            goals_away=int(ga),
        ))
    return matches, dataset_fingerprint(raw), n_finished
