"""Point d'entrée public de la gateway — la seule chose qu'axon-quant importe.

axon-quant ne manipule que des canonical_id ; toute la traduction vers/depuis
les IDs providers (identity_resolver), le fallback (fallback_chain) et la
normalisation restent internes à ce module (PRD §4.3quater, F12).
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.core.identity_data import TEAMS
from src.agents.quant.gateway.core.fallback_chain import fetch_league_data
from src.agents.quant.gateway.core.errors import NoDataAvailableError
from src.agents.quant.gateway.sports.registry import UnsupportedSportError
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


def search_team(name: str) -> dict | None:
    """Cherche une équipe par nom parmi les ligues couvertes en v1 (Ligue 1, Premier League)."""
    entity = _resolver.find_by_name(name)
    if entity is None:
        return None
    return {"canonical_id": entity.canonical_id, "name": entity.canonical_name}


def recent_form(canonical_team_id: str, *, competition_id: str,
                last: int = 10, season: str | None = None) -> list[dict]:
    """Forme récente d'une équipe DANS UNE COMPÉTITION DONNÉE.

    `competition_id` est REQUIS et vient de l'événement évalué, jamais de l'équipe.
    Une équipe appartient à plusieurs compétitions simultanément — le PSG joue en
    Ligue 1 et en Ligue des Champions la même semaine — et l'ancienne version
    choisissait le dataset en cherchant la première ligue contenant l'équipe. Deux
    conséquences, toutes deux silencieuses : un événement UEFA était servi avec la
    forme domestique, et une équipe hors des ligues onboardées était déclarée
    introuvable alors que son historique européen existait.

    La chaîne est désormais : événement -> compétition canonique -> couverture
    provider -> historique du participant. Aucun maillon ne part de l'équipe.

    En trêve estivale, peu ou pas de matchs "FINISHED" existent encore pour la
    saison à venir — pas un bug, un vrai manque de données.
    """
    season = season or current_season()
    # recent_form consomme les matchs JOUÉS → data_type RESULTS.
    envelope = fetch_league_data(
        sport="football",
        data_type="RESULTS",
        league_canonical_id=competition_id,
        season=season,
        resolver=_resolver,
    )
    # Calcul dérivé (pur) délégué à sports/football/derived.py — orchestration ici,
    # agrégation là-bas (frontière GW-FR-012).
    return derived.recent_form(envelope.payload.matches, canonical_team_id, competition_id, season, last)


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


@dataclass(frozen=True)
class DataFreshness:
    """Fraîcheur RÉELLE d'une donnée servie, calculée par la Gateway (GW-NFR-003).

    `effective_time` = l'horodatage sur lequel `freshness_score` est calculé
    (`freshness_basis` : published_time > event_time > fetched_at). `degraded=True`
    signale un repli sur `fetched_at` (base faible) : le consommateur NE doit pas
    interpréter cet horodatage comme une vraie fraîcheur. La Gateway CALCULE, le
    consommateur LIT — jamais de recomputation ailleurs."""
    freshness_score: float
    effective_time: datetime | None
    basis: str
    degraded: bool
    stale: bool


def _sport_of(competition_canonical_id: str) -> str | None:
    """`competition:baseball:usa:mlb` -> `baseball`. `None` si l'identifiant
    n'a pas la forme canonique — on ne devine pas un sport."""
    parties = (competition_canonical_id or "").split(":")
    return parties[1] if len(parties) >= 2 and parties[0] == "competition" else None


def data_freshness(
    league_canonical_id: str, season: str | None = None, data_type: str = "RESULTS",
    resolver: IdentityResolver | None = None,
) -> DataFreshness | None:
    """Fraîcheur de la donnée qui SERAIT servie pour cette compétition/saison.

    Réutilise le MÊME fetch que `recent_form`/`standings_strength` (la Gateway
    calcule `freshness_score` sur l'enveloppe) ; expose ses métadonnées sans les
    recalculer. `None` si aucune donnée disponible (jamais une fraîcheur fabriquée).

    `resolver` est INJECTABLE parce que le référentiel d'identités de ce module
    ne contient que des équipes de football. Un provider peut répondre
    parfaitement pour le hockey et voir chacune de ses rencontres écartée faute
    d'identité résolue : l'enveloppe sort vide, et le manque se lit « aucune
    donnée » alors que c'est le référentiel qui manquait. L'appelant qui connaît
    les sept sports passe le sien ; les entrées football historiques gardent le
    défaut. La Gateway n'importe pas pour autant la couche qui l'appelle.
    """
    season = season or current_season()
    # Le sport vient de l'identifiant de compétition, jamais d'un défaut : coder
    # « football » en dur faisait chercher des données de football pour une
    # compétition de baseball, obtenir NoDataAvailableError, et rendre `None`.
    # La fraîcheur devenait alors « inconnue » pour un motif faux — la Gateway ne
    # couvre tout simplement pas encore ce sport.
    sport = _sport_of(league_canonical_id)
    if sport is None:
        return None
    try:
        envelope = fetch_league_data(
            sport=sport, data_type=data_type,
            league_canonical_id=league_canonical_id, season=season,
            resolver=resolver or _resolver,
        )
    except (NoDataAvailableError, UnsupportedSportError):
        return None
    effective = getattr(envelope, envelope.freshness_basis, None)
    return DataFreshness(
        freshness_score=envelope.freshness_score,
        effective_time=effective,
        basis=envelope.freshness_basis,
        degraded=envelope.freshness_degraded,
        stale=envelope.stale,
    )
