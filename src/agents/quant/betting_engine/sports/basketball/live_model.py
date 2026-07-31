"""Basket NBA — modèle LIVE conforme au contrat `MarketModel` (wave finale §3).

Câble l'Elo (moneyline.py) dans le chemin live GÉNÉRIQUE (`evaluate_live_event`,
désormais neutre au marché). Point-in-time : les notes Elo ne dépendent que des matchs
STRICTEMENT antérieurs à la décision (sans fuite). Le modèle reste EXPERIMENTAL (verdict
dérivé du ledger — jamais SUPPORTED), donc la décision live reste ABSTAIN (BE-FR-011).

Identité basket = espace PROPRE (`team:basketball:usa:*`), IDs api-sports basketball
vérifiés en direct. Les 2 équipes All-Star (matchs d'exhibition) ne sont PAS mappées →
un event All-Star reste UNRESOLVED (isolé), jamais mal résolu.
"""

from __future__ import annotations

import functools
from datetime import datetime

from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity
from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent
from src.agents.quant.betting_engine.core.feature_set import EventFeatureSet
from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness,
    MarketPrediction,
    MarketSchema,
    PredictionExplanation,
    UncertaintyStatus,
)
from src.agents.quant.betting_engine.support_status import resolve_market_status
from src.agents.quant.betting_engine.sports.registry import SportModule
from .moneyline import HOME_EDGE, MIN_PRIOR_GAMES, _p_home, elo_ratings_as_of, load_nba_games

BASKET_MONEYLINE = MarketSchema("MATCH_WINNER", "2way", ("home", "away"), ("slot_1", "slot_2"), False)

# Identité NBA — IDs api-sports basketball vérifiés en direct (games 2022-23). Alias
# best-effort (Winamax NBA non vérifiable hors saison) : un alias absent => UNRESOLVED.
_NBA = [
    ("hawks", "132", "Atlanta Hawks", ["Atlanta"]), ("celtics", "133", "Boston Celtics", ["Boston"]),
    ("nets", "134", "Brooklyn Nets", ["Brooklyn"]), ("hornets", "135", "Charlotte Hornets", ["Charlotte"]),
    ("bulls", "136", "Chicago Bulls", ["Chicago"]), ("cavaliers", "137", "Cleveland Cavaliers", ["Cleveland"]),
    ("mavericks", "138", "Dallas Mavericks", ["Dallas"]), ("nuggets", "139", "Denver Nuggets", ["Denver"]),
    ("pistons", "140", "Detroit Pistons", ["Detroit"]), ("warriors", "141", "Golden State Warriors", ["Golden State"]),
    ("rockets", "142", "Houston Rockets", ["Houston"]), ("pacers", "143", "Indiana Pacers", ["Indiana"]),
    ("clippers", "144", "Los Angeles Clippers", ["LA Clippers"]), ("lakers", "145", "Los Angeles Lakers", ["LA Lakers"]),
    ("grizzlies", "146", "Memphis Grizzlies", ["Memphis"]), ("heat", "147", "Miami Heat", ["Miami"]),
    ("bucks", "148", "Milwaukee Bucks", ["Milwaukee"]), ("timberwolves", "149", "Minnesota Timberwolves", ["Minnesota"]),
    ("pelicans", "150", "New Orleans Pelicans", ["New Orleans"]), ("knicks", "151", "New York Knicks", ["New York"]),
    ("thunder", "152", "Oklahoma City Thunder", ["Oklahoma City"]), ("magic", "153", "Orlando Magic", ["Orlando"]),
    ("sixers", "154", "Philadelphia 76ers", ["Philadelphia"]), ("suns", "155", "Phoenix Suns", ["Phoenix"]),
    ("blazers", "156", "Portland Trail Blazers", ["Portland"]), ("kings", "157", "Sacramento Kings", ["Sacramento"]),
    ("spurs", "158", "San Antonio Spurs", ["San Antonio"]), ("raptors", "159", "Toronto Raptors", ["Toronto"]),
    ("jazz", "160", "Utah Jazz", ["Utah"]), ("wizards", "161", "Washington Wizards", ["Washington"]),
]

NBA_TEAMS: list[CanonicalEntity] = [
    CanonicalEntity(f"team:basketball:usa:{slug}", name, aliases, {"api_basketball": api_id})
    for slug, api_id, name, aliases in _NBA
]
_API_TO_CANONICAL: dict[str, str] = {api_id: f"team:basketball:usa:{slug}" for slug, api_id, _, _ in _NBA}


@functools.lru_cache(maxsize=1)
def _games():
    games, _fp = load_nba_games()
    return games


def build_basketball_features(event: CanonicalEvent, *, gateway, as_of: datetime) -> EventFeatureSet:
    """Features live = notes Elo point-in-time (matchs < as_of), par identité canonique.
    Une équipe sans historique suffisant est signalée `missing` (jamais une note inventée)."""
    ratings, played = elo_ratings_as_of(_games(), as_of)
    api_of = {v: k for k, v in _API_TO_CANONICAL.items()}   # canonical_id -> api id
    participant_features: dict[str, dict] = {}
    missing: set[str] = set()
    for p in event.participants:
        api_id = api_of.get(p.canonical_id)
        n = played.get(api_id, 0) if api_id else 0
        if api_id is None or n < MIN_PRIOR_GAMES:
            missing.add(f"elo_history_insufficient:{p.canonical_id}")
            continue
        participant_features[p.canonical_id] = {"elo_rating": ratings.get(api_id, 1500.0), "prior_games": n}
    return EventFeatureSet(
        event_id=event.event_id, sport="basketball", as_of=as_of,
        feature_set_version="basketball-elo-1.0", event_features={},
        participant_features=participant_features, matchup_features={}, missing_features=missing)


class BasketballMoneylineModel:
    sport = "basketball"
    market_type = "MATCH_WINNER"
    model_name = "basketball_moneyline"
    model_version = "basketball.moneyline.elo.v0"
    schema = BASKET_MONEYLINE
    _SELECTIONS = ("home", "away")

    def required_features(self) -> set[str]:
        return {"elo_rating", "prior_games"}

    def assess_data_readiness(self, event: CanonicalEvent, features: EventFeatureSet) -> DataReadiness:
        by_role = {p.role: p.canonical_id for p in event.participants}
        if "home" not in by_role or "away" not in by_role:
            return DataReadiness.INSUFFICIENT_DATA
        for role in ("home", "away"):
            pf = features.participant_features.get(by_role[role], {})
            if "elo_rating" not in pf or pf.get("prior_games", 0) < MIN_PRIOR_GAMES:
                return DataReadiness.INSUFFICIENT_DATA         # aucune note fabriquée
        # Plafond dérivé du ledger : EXPERIMENTAL tant qu'aucun SUPPORTED persisté.
        return resolve_market_status(self.model_name, self.model_version)

    def predict_selections(
        self, event: CanonicalEvent, features: EventFeatureSet, point_in_time: datetime
    ) -> dict[str, MarketPrediction]:
        by_role = {p.role: p.canonical_id for p in event.participants}
        rh = features.participant_features[by_role["home"]]["elo_rating"]
        ra = features.participant_features[by_role["away"]]["elo_rating"]
        ph = _p_home(rh, ra)
        readiness = self.assess_data_readiness(event, features)
        n_home = features.participant_features[by_role["home"]]["prior_games"]
        n_away = features.participant_features[by_role["away"]]["prior_games"]
        data_quality = round(min(1.0, min(n_home, n_away) / 40.0), 3)   # complétude d'historique réelle
        expl = PredictionExplanation(
            top_features=[("home_elo", round(rh, 2)), ("away_elo", round(ra, 2)),
                          ("home_edge", HOME_EDGE)],
            missing_features=set(features.missing_features),
            warnings=["modèle Elo EXPERIMENTAL — aucune mise réelle ; intervalle non estimé"],
            confidence_drivers=["Elo séquentiel sans fuite ; paramètres fixes (non fités sur l'éval)"])

        def mk(sel: str, p: float) -> MarketPrediction:
            return MarketPrediction(
                sport="basketball", market_type="MATCH_WINNER", selection=sel,
                fair_probability=p, probability_low=p, probability_high=p,
                uncertainty_status=UncertaintyStatus.NOT_ESTIMATED, model_version=self.model_version,
                data_quality=data_quality, calibration_status=readiness,
                point_in_time=point_in_time, explanation=expl)
        return {"home": mk("home", ph), "away": mk("away", 1.0 - ph)}


BASKETBALL_MODULE = SportModule("basketball", build_basketball_features, BasketballMoneylineModel())
