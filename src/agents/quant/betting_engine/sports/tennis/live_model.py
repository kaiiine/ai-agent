"""Tennis — modèle LIVE 2-way conforme au contrat `MarketModel` (Phase 5).

Câble l'Elo (elo_model.py) dans le chemin live GÉNÉRIQUE (`evaluate_live_event`). AUCUNE
logique spécifique tennis dans le pipeline : le sport neutre (pas de domicile) est déjà
porté par `ParticipantRoleResolver` (`player_a`/`player_b`) et le nombre d'issues par le
`MarketSchema` du modèle — exactement comme basket/hockey.

ATP et WTA sont deux MODÈLES distincts (pools et régimes différents) mais un seul SPORT
Winamax : le circuit est déduit de l'IDENTITÉ des joueurs (`player:tennis:{tour}:…`),
jamais d'un `if`. Deux joueurs de circuits différents (ou non résolus) -> features
manquantes -> INSUFFICIENT_DATA, jamais une probabilité fabriquée.

Point-in-time : les notes ne dépendent que des matchs STRICTEMENT antérieurs à la décision.
Le modèle reste EXPERIMENTAL (plafond dérivé du ledger) -> décision ABSTAIN (BE-FR-011).
"""

from __future__ import annotations

import functools
from datetime import datetime

from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent
from src.agents.quant.betting_engine.core.feature_set import EventFeatureSet
from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness,
    MarketPrediction,
    MarketSchema,
    PredictionExplanation,
    UncertaintyStatus,
)
from src.agents.quant.betting_engine.sports.sport_module import SportModule
from src.agents.quant.betting_engine.support_status import resolve_market_status

from .elo_model import ATP_PARAMS, WTA_PARAMS, _p, tennis_ratings_as_of
from .identity import tennis_players
from .tennis_data_loader import load_tennis_data

# Marché « Vainqueur » 2-way (betType 112 Winamax, vérifié en live). Issues = rôles neutres.
TENNIS_2WAY = MarketSchema("MATCH_WINNER", "2way", ("player_a", "player_b"),
                           ("slot_1", "slot_2"), False)

MODEL_NAME = "tennis_moneyline"
MODEL_VERSION = "tennis.moneyline.elo.v0"
_PARAMS = {"atp": ATP_PARAMS, "wta": WTA_PARAMS}


@functools.lru_cache(maxsize=2)
def _matches(tour: str):
    return load_tennis_data(tour).matches


@functools.lru_cache(maxsize=1)
def all_tennis_players():
    """Entités des DEUX circuits (espaces de noms séparés — aucun croisement possible)."""
    return tuple(tennis_players("atp")[0]) + tuple(tennis_players("wta")[0])


def _tour_of(canonical_id: str) -> str | None:
    parts = (canonical_id or "").split(":")
    return parts[2] if len(parts) == 4 and parts[0] == "player" and parts[1] == "tennis" else None


def build_tennis_features(event: CanonicalEvent, *, gateway, as_of: datetime) -> EventFeatureSet:
    """Features live = notes Elo point-in-time du circuit des DEUX joueurs."""
    ids = [p.canonical_id for p in event.participants]
    tours = {_tour_of(cid) for cid in ids}
    participant_features: dict[str, dict] = {}
    missing: set[str] = set()

    if len(tours) != 1 or None in tours:            # circuits mixtes/inconnus -> jamais d'inférence
        missing.add("tennis_tour_unresolved")
        return EventFeatureSet(
            event_id=event.event_id, sport="tennis", as_of=as_of,
            feature_set_version="tennis-elo-1.0", event_features={},
            participant_features={}, matchup_features={}, missing_features=missing)

    tour = tours.pop()
    params = _PARAMS[tour]
    _entities, dataset_of = tennis_players(tour)
    ratings, played = tennis_ratings_as_of(_matches(tour), as_of.date(), params)
    for p in event.participants:
        name = dataset_of.get(p.canonical_id)
        n = played.get(name, 0) if name else 0
        if not name or n < params.min_prior_matches:
            missing.add(f"elo_history_insufficient:{p.canonical_id}")
            continue
        participant_features[p.canonical_id] = {
            "elo_rating": ratings.get(name, params.init_rating), "prior_matches": n}
    return EventFeatureSet(
        event_id=event.event_id, sport="tennis", as_of=as_of,
        feature_set_version="tennis-elo-1.0", event_features={"tour": tour},
        participant_features=participant_features, matchup_features={}, missing_features=missing)


class TennisMoneylineModel:
    sport = "tennis"
    market_type = "MATCH_WINNER"
    model_name = MODEL_NAME
    model_version = MODEL_VERSION
    schema = TENNIS_2WAY
    _SELECTIONS = ("player_a", "player_b")

    def required_features(self) -> set[str]:
        return {"elo_rating", "prior_matches"}

    def assess_data_readiness(self, event: CanonicalEvent, features: EventFeatureSet) -> DataReadiness:
        by_role = {p.role: p.canonical_id for p in event.participants}
        if not set(self._SELECTIONS) <= set(by_role):
            return DataReadiness.INSUFFICIENT_DATA
        for role in self._SELECTIONS:
            pf = features.participant_features.get(by_role[role], {})
            if "elo_rating" not in pf:
                return DataReadiness.INSUFFICIENT_DATA     # aucune note fabriquée
        return resolve_market_status(self.model_name, self.model_version)

    def predict_selections(
        self, event: CanonicalEvent, features: EventFeatureSet, point_in_time: datetime
    ) -> dict[str, MarketPrediction]:
        by_role = {p.role: p.canonical_id for p in event.participants}
        fa = features.participant_features[by_role["player_a"]]
        fb = features.participant_features[by_role["player_b"]]
        pa = _p(fa["elo_rating"], fb["elo_rating"])
        readiness = self.assess_data_readiness(event, features)
        n = min(fa["prior_matches"], fb["prior_matches"])
        data_quality = round(min(1.0, n / 80.0), 3)          # complétude d'historique réelle
        expl = PredictionExplanation(
            top_features=[("player_a_elo", round(fa["elo_rating"], 1)),
                          ("player_b_elo", round(fb["elo_rating"], 1)),
                          ("tour", features.event_features.get("tour", "?"))],
            missing_features=set(features.missing_features),
            warnings=["modèle Elo tennis EXPERIMENTAL — aucune mise réelle ; intervalle non estimé"],
            confidence_drivers=["Elo sans fuite ; K fixe ; circuits ATP/WTA séparés ; "
                                "variantes surface/Glicko-2 mesurées non supérieures"])

        def mk(sel: str, p: float) -> MarketPrediction:
            return MarketPrediction(
                sport="tennis", market_type="MATCH_WINNER", selection=sel,
                fair_probability=p, probability_low=p, probability_high=p,
                uncertainty_status=UncertaintyStatus.NOT_ESTIMATED, model_version=self.model_version,
                data_quality=data_quality, calibration_status=readiness,
                point_in_time=point_in_time, explanation=expl)
        return {"player_a": mk("player_a", pa), "player_b": mk("player_b", 1.0 - pa)}


TENNIS_MODULE = SportModule("tennis", build_tennis_features, TennisMoneylineModel())
