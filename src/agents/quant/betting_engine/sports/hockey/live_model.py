"""Hockey NHL — modèle LIVE 3-way conforme au contrat `MarketModel` (finalization §1/§2).

Câble l'Elo+Davidson (regulation.py) dans le chemin live GÉNÉRIQUE (`evaluate_live_event`,
schema-driven 3-way). Point-in-time : notes + taux de nul issus des SEULS matchs
réglementaires strictement antérieurs (sans fuite). Le marché settle sur le RÉGLEMENTAIRE
(nul possible) — le harness 3-way le respecte. Modèle plafonné EXPERIMENTAL -> ABSTAIN.

Freshness : le chemin live générique consomme `Gateway.data_freshness` (Gateway mesure ->
BE lit), donc la fraîcheur devient MESURABLE pour le hockey comme pour le football — c'est
ce qui retire le blocker `measurable_live_freshness` (le dernier restant étant `positive_clv`).
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
from src.agents.quant.betting_engine.sports.sport_module import SportModule
from src.agents.quant.betting_engine.sports.threeway_davidson import (
    _nu, davidson_probs, regulation_ratings_as_of,
)
from .regulation import MODEL_NAME, MODEL_VERSION, NHL_PARAMS, load_nhl_regulation

HOCKEY_REG_3WAY = MarketSchema("MATCH_WINNER", "3way", ("home", "draw", "away"),
                               ("draw", "slot_1", "slot_2"), True)
_MIN_PRIOR = NHL_PARAMS.min_prior_games

# Identité NHL — IDs api-sports hockey vérifiés en direct (teams league 57). Les entrées
# « *_division » (matchs des étoiles) sont EXCLUES -> jamais mal résolues.
_NHL = [
    ("anaheim_ducks", "670"), ("arizona_coyotes", "671"), ("boston_bruins", "673"),
    ("buffalo_sabres", "674"), ("calgary_flames", "675"), ("carolina_hurricanes", "676"),
    ("chicago_blackhawks", "678"), ("colorado_avalanche", "679"), ("columbus_blue_jackets", "680"),
    ("dallas_stars", "681"), ("detroit_red_wings", "682"), ("edmonton_oilers", "683"),
    ("florida_panthers", "684"), ("los_angeles_kings", "685"), ("minnesota_wild", "687"),
    ("montreal_canadiens", "688"), ("nashville_predators", "689"), ("new_jersey_devils", "690"),
    ("new_york_islanders", "691"), ("new_york_rangers", "692"), ("ottawa_senators", "693"),
    ("philadelphia_flyers", "695"), ("pittsburgh_penguins", "696"), ("san_jose_sharks", "697"),
    ("st_louis_blues", "698"), ("tampa_bay_lightning", "699"), ("toronto_maple_leafs", "700"),
    ("vancouver_canucks", "701"), ("vegas_golden_knights", "702"), ("washington_capitals", "703"),
    ("winnipeg_jets", "704"), ("seattle_kraken", "1436"),
]

NHL_TEAMS: list[CanonicalEntity] = [
    CanonicalEntity(f"team:hockey:nhl:{slug}", slug.replace("_", " ").title(), [], {"api_hockey": api})
    for slug, api in _NHL
]
_API_OF: dict[str, str] = {f"team:hockey:nhl:{slug}": api for slug, api in _NHL}


@functools.lru_cache(maxsize=1)
def _games():
    games, _fp = load_nhl_regulation()
    return games


def build_hockey_features(event: CanonicalEvent, *, gateway, as_of: datetime) -> EventFeatureSet:
    ratings, played, draw_rate = regulation_ratings_as_of(_games(), as_of, NHL_PARAMS)
    participant_features: dict[str, dict] = {}
    missing: set[str] = set()
    for p in event.participants:
        api = _API_OF.get(p.canonical_id)
        n = played.get(api, 0) if api else 0
        if api is None or n < _MIN_PRIOR:
            missing.add(f"elo_history_insufficient:{p.canonical_id}")
            continue
        participant_features[p.canonical_id] = {"elo_rating": ratings.get(api, NHL_PARAMS.init_rating),
                                                 "prior_games": n}
    return EventFeatureSet(
        event_id=event.event_id, sport="hockey", as_of=as_of,
        feature_set_version="hockey-davidson-1.0", event_features={"draw_rate": round(draw_rate, 4)},
        participant_features=participant_features, matchup_features={}, missing_features=missing)


class HockeyRegulationModel:
    sport = "hockey"
    market_type = "MATCH_WINNER"
    model_name = MODEL_NAME
    model_version = MODEL_VERSION
    schema = HOCKEY_REG_3WAY
    _SELECTIONS = ("home", "draw", "away")

    def required_features(self) -> set[str]:
        return {"elo_rating", "prior_games"}

    def assess_data_readiness(self, event: CanonicalEvent, features: EventFeatureSet) -> DataReadiness:
        by_role = {p.role: p.canonical_id for p in event.participants}
        if "home" not in by_role or "away" not in by_role:
            return DataReadiness.INSUFFICIENT_DATA
        for role in ("home", "away"):
            pf = features.participant_features.get(by_role[role], {})
            if "elo_rating" not in pf or pf.get("prior_games", 0) < _MIN_PRIOR:
                return DataReadiness.INSUFFICIENT_DATA
        return resolve_market_status(self.model_name, self.model_version)

    def predict_selections(
        self, event: CanonicalEvent, features: EventFeatureSet, point_in_time: datetime
    ) -> dict[str, MarketPrediction]:
        by_role = {p.role: p.canonical_id for p in event.participants}
        rh = features.participant_features[by_role["home"]]["elo_rating"]
        ra = features.participant_features[by_role["away"]]["elo_rating"]
        nu = _nu(float(features.event_features.get("draw_rate", NHL_PARAMS.default_draw_rate)))
        probs = davidson_probs(rh, ra, NHL_PARAMS.home_edge, nu)
        readiness = self.assess_data_readiness(event, features)
        n = min(features.participant_features[by_role["home"]]["prior_games"],
                features.participant_features[by_role["away"]]["prior_games"])
        dq = round(min(1.0, n / 40.0), 3)
        expl = PredictionExplanation(
            top_features=[("home_elo", round(rh, 1)), ("away_elo", round(ra, 1)),
                          ("davidson_nu", round(nu, 3)), ("home_edge", NHL_PARAMS.home_edge)],
            missing_features=set(features.missing_features),
            warnings=["Davidson 3-way EXPERIMENTAL — résultat RÉGLEMENTAIRE (nul possible)"],
            confidence_drivers=["Elo+Davidson sans fuite ; ν point-in-time ; params fixes"])

        def mk(sel: str, p: float) -> MarketPrediction:
            return MarketPrediction(
                sport="hockey", market_type="MATCH_WINNER", selection=sel,
                fair_probability=p, probability_low=p, probability_high=p,
                uncertainty_status=UncertaintyStatus.NOT_ESTIMATED, model_version=self.model_version,
                data_quality=dq, calibration_status=readiness, point_in_time=point_in_time, explanation=expl)
        return {sel: mk(sel, probs[sel]) for sel in self._SELECTIONS}


HOCKEY_MODULE = SportModule("hockey", build_hockey_features, HockeyRegulationModel())
