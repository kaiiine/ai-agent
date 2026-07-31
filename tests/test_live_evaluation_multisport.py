"""`evaluate_live_event` NEUTRE au sport/marché (wave finale §1/§2) — hermétique.

Prouve que l'orchestrateur live n'est plus verrouillé 1X2/3-way : un module 2-way
(basket-like) traverse EXACTEMENT le même chemin générique (identité → canonical
market → features → modèle → décision) et produit des décisions 2-way. Le schéma de
marché est porté par le MODÈLE, jamais par un `if sport ==`. L'ordre des issues
bookmaker n'affecte ni les probabilités ni la décision.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness, MarketPrediction, MarketSchema, PredictionExplanation, UncertaintyStatus,
)
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
    evaluate_live_event,
)
from src.agents.quant.betting_engine.sports.registry import SportModule

_DECISION = datetime(2026, 1, 4, 12, tzinfo=timezone.utc)
_TIPOFF = datetime(2026, 1, 5, 1, tzinfo=timezone.utc)
_HOME = "team:basketball:usa:celtics"
_AWAY = "team:basketball:usa:lakers"
_BASKET_2WAY = MarketSchema("MATCH_WINNER", "2way", ("home", "away"), ("slot_1", "slot_2"), False)


class _Features:
    def __init__(self, as_of):
        self.as_of = as_of


class _EloStubModel:
    """Modèle 2-way synthétique : déclare un schéma 2-way, plafonné EXPERIMENTAL."""
    sport = "basketball"
    market_type = "MATCH_WINNER"
    model_name = "basketball_moneyline"
    model_version = "elo.v0"
    schema = _BASKET_2WAY

    def assess_data_readiness(self, event, features):
        return DataReadiness.EXPERIMENTAL

    def predict_selections(self, event, features, point_in_time):
        expl = PredictionExplanation([], set(), [], [])

        def mk(sel, p):
            return MarketPrediction("basketball", "MATCH_WINNER", sel, p, p, p,
                                    UncertaintyStatus.NOT_ESTIMATED, "elo.v0", 0.9,
                                    DataReadiness.EXPERIMENTAL, point_in_time, expl)
        return {"home": mk("home", 0.60), "away": mk("away", 0.40)}


def _build_feature_set(event, *, gateway, as_of):
    return _Features(as_of)


_MODULE = SportModule("basketball", _build_feature_set, _EloStubModel())


def _resolver():
    identity = IdentityResolver([
        CanonicalEntity(_HOME, "Boston Celtics", ["Celtics"], {}),
        CanonicalEntity(_AWAY, "Los Angeles Lakers", ["LA Lakers"], {}),
    ])
    comp = lambda tid: (("competition:basketball:usa:nba", "RESOLVED", "competition_table")
                        if tid == "NBA" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _moneyline_market(home_odds=1.80, away_odds=2.10, reverse=False):
    sels = [RawSelection("1", "Celtics", home_odds, "slot_1"),
            RawSelection("2", "LA Lakers", away_odds, "slot_2")]     # 2 issues, PAS de nul
    if reverse:
        sels = list(reversed(sels))
    return RawMarket(MarketType.MATCH_WINNER, 3178, "Vainqueur", "2way", False, None, sels)


def _event(reverse=False):
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="NBA1", sport="basketball", competition="NBA",
        slot_1_name="Celtics", slot_2_name="LA Lakers", slot_1_id="1", slot_2_id="2",
        start_time=_TIPOFF, status="PREMATCH", is_outright=False,
        markets=[_moneyline_market(reverse=reverse)], fetched_at=_DECISION, raw_tournament_id="NBA")


def _run(event=None):
    return evaluate_live_event(
        event or _event(), decision_time=_DECISION, event_resolver=_resolver(),
        sports_gateway=object(), sport_modules={"basketball": _MODULE},
        coverage_check=lambda comp, season, dt: ["api_sports"])


def test_two_way_sport_flows_through_generic_live_path():
    res = _run()
    assert res.status is S.EVALUATED                       # même chemin générique que le football
    # DEUX issues (home/away), aucune "draw" fabriquée pour un marché 2-way.
    assert set(res.predictions) == {"home", "away"}
    assert {d.selection for d in res.decisions} == {"home", "away"}
    # Cap BE-FR-011 : EXPERIMENTAL -> ABSTAIN (jamais BET), sport-neutre.
    assert all(d.decision == "ABSTAIN" for d in res.decisions)
    # La cote a bien suivi le rôle canonique (home = Celtics @ 1.80).
    home = next(d for d in res.decisions if d.selection == "home")
    assert home.bookmaker_odds == 1.80 and home.market_type == "MATCH_WINNER"


def test_bookmaker_selection_order_does_not_change_outcome():
    # Mêmes sélections 2-way inversées -> mêmes probabilités par identité, même décision (§2).
    a = {d.selection: (d.model_probability, d.decision, d.bookmaker_odds) for d in _run(_event()).decisions}
    b = {d.selection: (d.model_probability, d.decision, d.bookmaker_odds)
         for d in _run(_event(reverse=True)).decisions}
    assert a == b


def test_three_way_market_rejected_for_two_way_schema():
    # Un marché 3-way présenté à un modèle 2-way n'est PAS canonicalisé (schéma non conforme).
    three_way = RawMarket(
        MarketType.MATCH_WINNER, 3178, "Résultat", "3way", False, None,
        [RawSelection("1", "Celtics", 1.8, "slot_1"), RawSelection("x", "Nul", 3.4, "draw"),
         RawSelection("2", "LA Lakers", 2.1, "slot_2")])
    ev = _event()
    ev = RawBookmakerEvent(**{**ev.__dict__, "markets": [three_way]})
    assert _run(ev).status is S.MARKET_CANONICALIZATION_FAILED
