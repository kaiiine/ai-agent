"""Football V0 : `CanonicalEvent` -> `EventFeatureSet`, à partir de la gateway.

Consomme UNIQUEMENT l'API publique de la gateway, par `canonical_id` (jamais par
nom) : `recent_form()` par participant et `standings_strength()` une fois par
événement. Ne plante jamais sur donnée manquante — dégrade et remonte dans
`missing_features` (ex. trêve estivale = vrai manque, pas un bug).

Forces Dixon-Coles (`attack_strength`/`defense_strength`) émises ici : ce sont
des FEATURES (fait brut -> quantité dérivée, §6.2). Le calcul `team_strengths`
est importé de `quant/dixon_coles.py` (import transitoire, todo #7 — jamais
copié, source unique gelée et testée). La forme brute reste interne : seules les
forces (neutres de lieu) sont exposées ; le MarketModel ne voit jamais la forme.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from src.agents.quant.gateway.core.errors import NoDataAvailableError
from src.agents.quant.dixon_coles import team_strengths  # import transitoire (todo #7)
from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent
from src.agents.quant.betting_engine.core.feature_set import EventFeatureSet, FeatureValue

from ..manifest import FEATURE_SET_VERSION

FORM_WINDOW = 10          # derniers matchs joués (cf. gateway.recent_form last=10)
MIN_FORM_MATCHES = 5      # en-dessous, forme calculée mais signalée peu fiable


class _GatewayLike(Protocol):
    # `competition_id` est passé explicitement : la compétition est une propriété de
    # l'ÉVÉNEMENT, jamais de l'équipe. Une équipe joue dans plusieurs compétitions
    # la même semaine — dériver le dataset depuis l'équipe servait la forme
    # domestique à un événement européen, sans erreur ni trace.
    def recent_form(self, canonical_team_id: str, *, competition_id: str,
                    last: int, season: str) -> list[dict]: ...
    def standings_strength(self, league_canonical_id: str, season: str) -> dict[str, float]: ...


def _season_of(scheduled_at: datetime) -> str:
    """Saison foot européen : mois >= 7 -> année courante, sinon année - 1."""
    return str(scheduled_at.year if scheduled_at.month >= 7 else scheduled_at.year - 1)


def _form_stats(form: list[dict]) -> dict[str, FeatureValue]:
    """Stats de forme du point de vue de l'équipe (fonction pure de la forme)."""
    wins = draws = 0
    goals_for = goals_against = 0
    for match in form:
        if match["is_home"]:
            mine, opp = match["goals_home"], match["goals_away"]
        else:
            mine, opp = match["goals_away"], match["goals_home"]
        goals_for += mine
        goals_against += opp
        if mine > opp:
            wins += 1
        elif mine == opp:
            draws += 1
    n = len(form)
    return {
        "form_matches": n,
        "form_points_per_game": round((3 * wins + draws) / n, 3),
        "form_goals_for_avg": round(goals_for / n, 3),
        "form_goals_against_avg": round(goals_against / n, 3),
        "form_goal_diff_avg": round((goals_for - goals_against) / n, 3),
        "form_win_rate": round(wins / n, 3),
    }


def build_event_feature_set(
    event: CanonicalEvent,
    gateway: _GatewayLike | None = None,
    *,
    as_of: datetime,
    window: int = FORM_WINDOW,
) -> EventFeatureSet:
    """`as_of` est REQUIS : le cutoff de données déclaré par l'appelant (instant
    jusqu'auquel l'information est disponible), pas le coup d'envoi. C'est lui qui
    permet la garde anti-fuite en aval (features.as_of ≤ point_in_time, ADR-004) ;
    le déduire de `scheduled_at` (postérieur à la décision) la rendrait fausse.
    Aucune substitution implicite par l'heure courante."""
    if gateway is None:                       # import paresseux : hermétique en test
        from src.agents.quant.gateway import gateway as gateway  # type: ignore

    season = _season_of(event.scheduled_at)
    missing: set[str] = set()

    try:
        standings = gateway.standings_strength(event.competition_id, season)
    except NoDataAvailableError:
        standings = {}

    participant_features: dict[str, dict[str, FeatureValue]] = {}
    for participant in event.participants:
        cid = participant.canonical_id
        features: dict[str, FeatureValue] = {}

        try:
            form = gateway.recent_form(
                cid, competition_id=event.competition_id, last=window, season=season)
        except NoDataAvailableError:
            form = []

        if not form:
            missing.add(f"form:{cid}")
            missing.add(f"rest_days:{cid}")
        else:
            features.update(_form_stats(form))
            features["rest_days"] = (
                event.scheduled_at.date() - date.fromisoformat(form[0]["date"])
            ).days
            # Forces Dixon-Coles (features neutres de lieu) : mêmes appels que le
            # pipeline gelé (opponent_ratings = classement, ou None si absent ->
            # ajustement adversaire désactivé, fallback identique).
            strengths = team_strengths(form, opponent_ratings=standings or None)
            features["attack_strength"] = strengths["attack"]
            features["defense_strength"] = strengths["defense"]
            if features["form_matches"] < MIN_FORM_MATCHES:
                missing.add(f"form_insufficient:{cid}")

        strength = standings.get(cid)
        if strength is None:
            missing.add(f"standings:{cid}")
        else:
            features["standings_strength"] = strength

        participant_features[cid] = features

    return EventFeatureSet(
        event_id=event.event_id,
        sport=event.sport,
        as_of=as_of,
        feature_set_version=FEATURE_SET_VERSION,
        event_features={},                     # V0 : signal en participant + matchup
        participant_features=participant_features,
        matchup_features=_matchup_features(event, participant_features),
        missing_features=missing,
    )


def _matchup_features(
    event: CanonicalEvent, participant_features: dict[str, dict[str, FeatureValue]]
) -> dict[str, FeatureValue]:
    """Différentiels home - away, calculés seulement si les deux valeurs existent."""
    by_role = {p.role: p.canonical_id for p in event.participants}
    home, away = by_role.get("home"), by_role.get("away")
    if home is None or away is None:
        return {}

    home_f = participant_features.get(home, {})
    away_f = participant_features.get(away, {})
    matchup: dict[str, FeatureValue] = {}
    for feature, out in (
        ("standings_strength", "strength_differential"),
        ("form_points_per_game", "form_ppg_differential"),
        ("form_goal_diff_avg", "form_goal_diff_differential"),
    ):
        if feature in home_f and feature in away_f:
            matchup[out] = round(float(home_f[feature]) - float(away_f[feature]), 3)
    return matchup
