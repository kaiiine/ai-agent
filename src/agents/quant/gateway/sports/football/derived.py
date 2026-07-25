"""Datasets dérivés football (PRD v2 §5.3, GW-FR-012).

Fonctions PURES et déterministes des faits canoniques (+ une fenêtre) : aucun
paramètre appris, aucun appel réseau, aucune I/O. L'orchestration (résolution
de ligue, fetch provider) reste dans gateway.py, qui délègue ici le calcul.

Déplacé depuis gateway.py (v1) : la logique numérique est identique, seule la
frontière fait/orchestration est rendue explicite.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

from src.agents.quant.gateway.sports.football.canonical_facts import (
    CanonicalMatch,
    CanonicalStandingRow,
)

RECENT_FORM_VERSION = "1.0"
STANDINGS_STRENGTH_VERSION = "1.0"


def recent_form(
    matches: list[CanonicalMatch],
    team_id: str,
    league_id: str,
    season: str,
    last: int = 10,
) -> list[dict]:
    """Les `last` derniers matchs JOUÉS d'une équipe, du plus récent au plus ancien.

    Fonction pure : ne prend que des faits (matches) et des paramètres de fenêtre.
    """
    finished = [
        m for m in matches
        if m.status == "FINISHED"
        and team_id in (m.home_team_id, m.away_team_id)
        and m.goals_home is not None
        and m.goals_away is not None
    ]
    finished.sort(key=lambda m: m.kickoff, reverse=True)

    form = []
    for match in finished[:last]:
        is_home = match.home_team_id == team_id
        form.append({
            "date": match.kickoff.date().isoformat(),
            "opponent_id": match.away_team_id if is_home else match.home_team_id,
            "goals_home": match.goals_home,
            "goals_away": match.goals_away,
            "is_home": is_home,
            "league_id": league_id,
            "season": season,
        })
    return form


def standings_strength(rows: list[CanonicalStandingRow]) -> dict[str, float]:
    """Proxy de force par équipe depuis un classement : 1er → 1.3, dernier → 0.7 (linéaire).

    Fonction pure des lignes de classement. {} si moins de 2 équipes.
    """
    if len(rows) < 2:
        return {}
    n = len(rows)
    return {row.team_id: round(1.3 - 0.6 * (row.rank - 1) / (n - 1), 3) for row in rows}


@dataclass(frozen=True)
class Calculator:
    """Calculateur dérivé nommé et versionné (satisfait le protocole DerivedCalculator)."""
    name: str
    version: str
    compute: Callable

    def __call__(self, *args, **kwargs):
        return self.compute(*args, **kwargs)


CALCULATORS: dict[str, Calculator] = {
    "recent_form": Calculator("recent_form", RECENT_FORM_VERSION, recent_form),
    "standings_strength": Calculator("standings_strength", STANDINGS_STRENGTH_VERSION, standings_strength),
}
