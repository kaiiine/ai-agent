"""Baseball / NFL / Volley LIVE câblés (§9/§10/§11) — les VRAIS modèles Elo 2-way
traversent le chemin live générique AVEC fraîcheur mesurée. Hermétique (fixtures réelles
embarquées, zéro réseau). Une seule table de cas : même harness, params/identité par sport.

Prouve par sport : Winamax event -> identité (dérivée des données) -> Elo point-in-time ->
probas home/away -> EXPERIMENTAL -> ABSTAIN (BE-FR-011), freshness Gateway->BE mesurée,
équipe hors-roster isolée, cold-start avant saison -> aucune probabilité fabriquée.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
    evaluate_live_event,
)
from src.agents.quant.betting_engine.sports.american_football.live_model import NFL_MODULE, NFL_TEAMS
from src.agents.quant.betting_engine.sports.baseball.live_model import BASEBALL_MODULE, MLB_TEAMS
from src.agents.quant.betting_engine.sports.volleyball.live_model import VOLLEYBALL_MODULE, VOLLEY_TEAMS

_UTC = timezone.utc

CASES = {
    "baseball": dict(
        module=BASEBALL_MODULE, teams=MLB_TEAMS, sport="baseball",
        home="Boston Red Sox", away="Minnesota Twins", comp_tid="MLB",
        canonical="competition:baseball:usa:mlb", min_prior=20,
        decision=datetime(2022, 7, 1, 12, tzinfo=_UTC), faceoff=datetime(2022, 7, 2, 0, tzinfo=_UTC),
        preseason=datetime(2022, 3, 1, tzinfo=_UTC)),
    "american_football": dict(
        module=NFL_MODULE, teams=NFL_TEAMS, sport="american_football",
        home="Las Vegas Raiders", away="Cincinnati Bengals", comp_tid="NFL",
        canonical="competition:american_football:usa:nfl", min_prior=6,
        decision=datetime(2022, 12, 1, 12, tzinfo=_UTC), faceoff=datetime(2022, 12, 4, 18, tzinfo=_UTC),
        preseason=datetime(2022, 7, 1, tzinfo=_UTC)),
    "volleyball": dict(
        module=VOLLEYBALL_MODULE, teams=VOLLEY_TEAMS, sport="volleyball",
        home="Vero Volley W", away="Bergamo W", comp_tid="VOL",
        canonical="competition:volleyball:ita:serie_a1", min_prior=5,
        decision=datetime(2023, 1, 15, 12, tzinfo=_UTC), faceoff=datetime(2023, 1, 16, 18, tzinfo=_UTC),
        preseason=datetime(2022, 8, 1, tzinfo=_UTC)),
}


class _Freshness:
    def __init__(self, effective_time):
        self.effective_time, self.freshness_score, self.degraded = effective_time, 0.9, False


class _Gateway:
    def __init__(self, decision):
        self._decision = decision

    def data_freshness(self, competition_id, season):
        return _Freshness(self._decision - timedelta(hours=2))    # récent -> mesuré, non stale


def _resolver(case):
    comp = lambda tid: ((case["canonical"], "RESOLVED", "competition_table")
                        if tid == case["comp_tid"] else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(IdentityResolver(case["teams"]), competition_resolver=comp)


def _event(case, s1=None, s2=None):
    s1, s2 = s1 or case["home"], s2 or case["away"]
    market = RawMarket(MarketType.MATCH_WINNER, 3178, "Vainqueur", "2way", False, None,
                       [RawSelection("1", s1, 1.80, "slot_1"), RawSelection("2", s2, 2.10, "slot_2")])
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="EVT", sport=case["sport"], competition=case["comp_tid"],
        slot_1_name=s1, slot_2_name=s2, slot_1_id="1", slot_2_id="2",
        start_time=case["faceoff"], status="PREMATCH", is_outright=False,
        markets=[market], fetched_at=case["decision"], raw_tournament_id=case["comp_tid"])


def _run(case, event=None, *, decision=None, gateway=None):
    dt = decision or case["decision"]
    return evaluate_live_event(
        event or _event(case), decision_time=dt, event_resolver=_resolver(case),
        sports_gateway=gateway if gateway is not None else _Gateway(dt),
        sport_modules={case["sport"]: case["module"]},
        coverage_check=lambda comp, season, dt: ["api_sports"])


@pytest.mark.parametrize("key", list(CASES))
def test_real_model_evaluates_2way_with_measured_freshness(key):
    case = CASES[key]
    res = _run(case)
    assert res.status is S.EVALUATED
    assert set(res.predictions) == {"home", "away"}         # 2-way, aucun nul
    ph = res.predictions["home"].fair_probability
    assert 0.0 < ph < 1.0 and abs(ph + res.predictions["away"].fair_probability - 1.0) < 1e-9
    assert res.predictions["home"].calibration_status.value == "EXPERIMENTAL"
    assert all(d.decision == "ABSTAIN" for d in res.decisions)   # cap BE-FR-011
    assert res.freshness_score == 0.9                            # §14 Gateway->BE mesurée


@pytest.mark.parametrize("key", list(CASES))
def test_point_in_time_features_use_only_prior_games(key):
    case = CASES[key]
    fs = _run(case).feature_set
    assert fs.as_of == case["decision"] and fs.sport == case["sport"]
    assert all(pf["prior_games"] >= case["min_prior"] for pf in fs.participant_features.values())


@pytest.mark.parametrize("key", list(CASES))
def test_non_roster_team_isolated(key):
    case = CASES[key]
    res = _run(case, _event(case, s1="Paris Saint-Germain"))    # hors roster du sport
    assert res.status is S.EVENT_NOT_RESOLVED


@pytest.mark.parametrize("key", list(CASES))
def test_cold_start_before_season_abstains_without_fabrication(key):
    case = CASES[key]
    res = _run(case, decision=case["preseason"], gateway=object())
    assert res.status is S.INSUFFICIENT_FEATURES               # aucune note fabriquée
