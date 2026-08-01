"""Câblage LIVE GÉNÉRIQUE des sports moneyline 2-way (Elo pairwise) — §9/§10/§11.

Une SEULE implémentation du chemin live (identité + feature builder Elo point-in-time +
modèle `MarketModel` 2-way) pour baseball, NFL et volley. Chaque sport fournit ses
DONNÉES (fixture réelle), ses PARAMÈTRES Elo (jamais copiés d'un autre sport) et son
identité — dérivée DIRECTEMENT de la fixture, donc AUCUNE whitelist de compétition en
dur (§11) : toute équipe présente dans les données du sport résout ; d'autres
compétitions entrent en AJOUTANT des données/identités, pas en modifiant ce code.

Sans fuite par construction : les notes Elo ne dépendent que des matchs strictement
antérieurs à la décision. Le modèle reste EXPERIMENTAL (plafond dérivé du ledger) donc la
décision live reste ABSTAIN (BE-FR-011). Aucune probabilité fabriquée : une équipe sans
historique suffisant est signalée `missing`, jamais notée par défaut.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

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
from src.agents.quant.betting_engine.sports.pairwise_elo import EloParams, elo_ratings_as_of, p_home
from src.agents.quant.betting_engine.sports.sport_module import SportModule

# Marché « Vainqueur » 2-way (aucun nul) — sémantique Winamax vérifiée (NFL/AFL/volley/baseball).
MONEYLINE_2WAY = MarketSchema("MATCH_WINNER", "2way", ("home", "away"), ("slot_1", "slot_2"), False)


def team_directory(path: Path, *, id_home: str, id_away: str, name_home: str, name_away: str,
                   exclude: frozenset[str] = frozenset()) -> dict[str, str]:
    """`{api_id -> nom}` de TOUTES les équipes présentes dans la fixture d'un sport.
    L'identité live est donc dérivée des DONNÉES (jamais une liste codée en dur), ce qui
    rend l'ajout d'une compétition = ajout de données. `exclude` retire les pseudo-équipes
    d'exhibition (matchs des étoiles : « American League », …) -> isolées, jamais résolues."""
    data = json.loads(Path(path).read_bytes())
    directory: dict[str, str] = {}
    for g in data["games"]:
        for id_key, name_key in ((id_home, name_home), (id_away, name_away)):
            name = str(g[name_key])
            if name not in exclude:
                directory[str(g[id_key])] = name
    return directory


def build_identity(directory: dict[str, str], *, sport: str, league: str, meta_key: str):
    """(`CanonicalEntity` liste, `canonical_id -> api_id`) depuis un annuaire d'équipes.
    Slug canonique = api_id (unicité garantie, aucune collision de noms)."""
    teams = [
        CanonicalEntity(f"team:{sport}:{league}:{api}", name, [], {meta_key: api})
        for api, name in sorted(directory.items())
    ]
    api_of = {f"team:{sport}:{league}:{api}": api for api in directory}
    return teams, api_of


def make_feature_builder(*, sport: str, games_fn: Callable, api_of: dict[str, str],
                         params: EloParams, feature_version: str) -> Callable:
    """Feature builder live = notes Elo point-in-time (matchs < as_of) par identité
    canonique. Réutilise l'UNIQUE implémentation Elo du harness (aucune duplication)."""
    def build(event: CanonicalEvent, *, gateway, as_of: datetime) -> EventFeatureSet:
        ratings, played = elo_ratings_as_of(games_fn(), as_of, params)
        participant_features: dict[str, dict] = {}
        missing: set[str] = set()
        for p in event.participants:
            api = api_of.get(p.canonical_id)
            n = played.get(api, 0) if api else 0
            if api is None or n < params.min_prior_games:
                missing.add(f"elo_history_insufficient:{p.canonical_id}")
                continue
            participant_features[p.canonical_id] = {
                "elo_rating": ratings.get(api, params.init_rating), "prior_games": n}
        return EventFeatureSet(
            event_id=event.event_id, sport=sport, as_of=as_of,
            feature_set_version=feature_version, event_features={},
            participant_features=participant_features, matchup_features={}, missing_features=missing)
    return build


class PairwiseLiveModel:
    """Modèle live 2-way GÉNÉRIQUE piloté par les paramètres Elo d'un sport. Identique en
    structure au modèle basket/hockey ; seuls sport/params/identité changent."""
    market_type = "MATCH_WINNER"
    schema = MONEYLINE_2WAY
    _SELECTIONS = ("home", "away")

    def __init__(self, *, sport: str, model_name: str, model_version: str, params: EloParams):
        self.sport = sport
        self.model_name = model_name
        self.model_version = model_version
        self.params = params

    def required_features(self) -> set[str]:
        return {"elo_rating", "prior_games"}

    def assess_data_readiness(self, event: CanonicalEvent, features: EventFeatureSet) -> DataReadiness:
        by_role = {p.role: p.canonical_id for p in event.participants}
        if "home" not in by_role or "away" not in by_role:
            return DataReadiness.INSUFFICIENT_DATA
        for role in ("home", "away"):
            pf = features.participant_features.get(by_role[role], {})
            if "elo_rating" not in pf or pf.get("prior_games", 0) < self.params.min_prior_games:
                return DataReadiness.INSUFFICIENT_DATA          # aucune note fabriquée
        return resolve_market_status(self.model_name, self.model_version)   # plafond ledger

    def predict_selections(
        self, event: CanonicalEvent, features: EventFeatureSet, point_in_time: datetime
    ) -> dict[str, MarketPrediction]:
        by_role = {p.role: p.canonical_id for p in event.participants}
        rh = features.participant_features[by_role["home"]]["elo_rating"]
        ra = features.participant_features[by_role["away"]]["elo_rating"]
        ph = p_home(rh, ra, self.params)
        readiness = self.assess_data_readiness(event, features)
        n = min(features.participant_features[by_role["home"]]["prior_games"],
                features.participant_features[by_role["away"]]["prior_games"])
        data_quality = round(min(1.0, n / (self.params.min_prior_games * 4)), 3)
        expl = PredictionExplanation(
            top_features=[("home_elo", round(rh, 1)), ("away_elo", round(ra, 1)),
                          ("home_edge", self.params.home_edge)],
            missing_features=set(features.missing_features),
            warnings=[f"modèle Elo {self.sport} EXPERIMENTAL — aucune mise réelle ; intervalle non estimé"],
            confidence_drivers=["Elo pairwise sans fuite ; paramètres fixes propres au sport (non fités)"])

        def mk(sel: str, p: float) -> MarketPrediction:
            return MarketPrediction(
                sport=self.sport, market_type="MATCH_WINNER", selection=sel,
                fair_probability=p, probability_low=p, probability_high=p,
                uncertainty_status=UncertaintyStatus.NOT_ESTIMATED, model_version=self.model_version,
                data_quality=data_quality, calibration_status=readiness,
                point_in_time=point_in_time, explanation=expl)
        return {"home": mk("home", ph), "away": mk("away", 1.0 - ph)}


def make_module(*, sport: str, games_fn: Callable, api_of: dict[str, str], params: EloParams,
                model_name: str, model_version: str, feature_version: str) -> SportModule:
    """Assemble le `SportModule` live d'un sport moneyline 2-way."""
    builder = make_feature_builder(sport=sport, games_fn=games_fn, api_of=api_of,
                                   params=params, feature_version=feature_version)
    model = PairwiseLiveModel(sport=sport, model_name=model_name,
                              model_version=model_version, params=params)
    return SportModule(sport, builder, model)
