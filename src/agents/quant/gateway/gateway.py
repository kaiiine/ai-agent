"""Point d'entrée public de la gateway — la seule chose qu'axon-quant importe.

axon-quant ne manipule que des canonical_id ; toute la traduction vers/depuis
les IDs providers (identity_resolver), le fallback (fallback_chain) et la
normalisation restent internes à ce module (PRD §4.3quater, F12).
"""

from __future__ import annotations
from datetime import date

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.core.identity_data import TEAMS, LEAGUE_TEAMS
from src.agents.quant.gateway.core.fallback_chain import fetch_league_data
from src.agents.quant.gateway.core.errors import NoDataAvailableError
from src.agents.quant.gateway.sports.football import derived

# Le résolveur ne contient que des ÉQUIPES : les compétitions vivent dans
# competition_registry (identité) + provider_coverage_registry (mapping provider),
# jamais ici (GW-FR-002).
_resolver = IdentityResolver(TEAMS)


def current_season() -> str:
    """Convention saison foot européen : "2025" = août 2025 → mai 2026."""
    today = date.today()
    year = today.year if today.month >= 7 else today.year - 1
    return str(year)


def _team_league(team_canonical_id: str) -> str | None:
    for league_id, team_ids in LEAGUE_TEAMS.items():
        if team_canonical_id in team_ids:
            return league_id
    return None


def search_team(name: str) -> dict | None:
    """Cherche une équipe par nom parmi les ligues couvertes en v1 (Ligue 1, Premier League)."""
    entity = _resolver.find_by_name(name)
    if entity is None:
        return None
    return {"canonical_id": entity.canonical_id, "name": entity.canonical_name}


def recent_form(canonical_team_id: str, last: int = 10, season: str | None = None) -> list[dict]:
    """Forme récente, dérivée localement d'un fetch batch par ligue (jamais par équipe — F13).

    En période de trêve estivale, peu ou pas de matchs "FINISHED" existent
    encore pour la saison à venir — pas un bug, un vrai manque de données.
    """
    league_id = _team_league(canonical_team_id)
    if league_id is None:
        raise NoDataAvailableError(
            f"Équipe {canonical_team_id} hors des ligues couvertes en v1 (Ligue 1, Premier League)"
        )

    season = season or current_season()
    # recent_form consomme les matchs JOUÉS → data_type RESULTS.
    envelope = fetch_league_data(
        sport="football",
        data_type="RESULTS",
        league_canonical_id=league_id,
        season=season,
        resolver=_resolver,
    )
    # Calcul dérivé (pur) délégué à sports/football/derived.py — orchestration ici,
    # agrégation là-bas (frontière GW-FR-012).
    return derived.recent_form(envelope.payload.matches, canonical_team_id, league_id, season, last)


def standings_strength(league_canonical_id: str, season: str | None = None) -> dict[str, float]:
    """Proxy de force par équipe depuis le classement : 1er → 1.3, dernier → 0.7.

    ⚠ Classement ACTUEL de la saison, pas celui à la date de chaque match de
    forme — acceptable en usage live, à reconstruire en point-in-time strict
    avant tout backtest (même limitation que documentée avant cette gateway).
    """
    season = season or current_season()
    envelope = fetch_league_data(
        sport="football",
        data_type="STANDINGS",
        league_canonical_id=league_canonical_id,
        season=season,
        resolver=_resolver,
    )
    return derived.standings_strength(envelope.payload.standings)


def opponent_ratings_for_form(form: list[dict]) -> dict[str, float]:
    """Construit {opponent_canonical_id: force} pour une forme donnée. {} si indisponible."""
    if not form:
        return {}
    try:
        return standings_strength(form[0]["league_id"], form[0]["season"])
    except Exception:
        return {}
