"""Basket LIVE câblé (wave finale §3) — le VRAI modèle Elo traverse le chemin live
générique. Hermétique (fixture réelle embarquée, zéro réseau).

Winamax basketball event → identité NBA → features Elo POINT-IN-TIME → modèle →
décision. Le modèle réel restant EXPERIMENTAL, la décision est ABSTAIN (BE-FR-011),
mais le chemin est techniquement complet. Aucune note Elo n'utilise un match postérieur.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
    evaluate_live_event,
)
from src.agents.quant.betting_engine.sports.basketball.live_model import BASKETBALL_MODULE, NBA_TEAMS

# Mi-saison 2022-23 : Celtics/Lakers ont largement > 10 matchs antérieurs.
_DECISION = datetime(2023, 3, 1, 12, tzinfo=timezone.utc)
_TIPOFF = datetime(2023, 3, 2, 2, tzinfo=timezone.utc)


def _resolver():
    comp = lambda tid: (("competition:basketball:usa:nba", "RESOLVED", "competition_table")
                        if tid == "NBA" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(IdentityResolver(NBA_TEAMS), competition_resolver=comp)


def _moneyline(home_odds=1.80, away_odds=2.10):
    return RawMarket(MarketType.MATCH_WINNER, 3178, "Vainqueur", "2way", False, None,
                     [RawSelection("1", "Boston Celtics", home_odds, "slot_1"),
                      RawSelection("2", "Los Angeles Lakers", away_odds, "slot_2")])


def _event(slot_1="Boston Celtics", slot_2="Los Angeles Lakers"):
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="NBA_BOS_LAL", sport="basketball", competition="NBA",
        slot_1_name=slot_1, slot_2_name=slot_2, slot_1_id="1", slot_2_id="2",
        start_time=_TIPOFF, status="PREMATCH", is_outright=False,
        markets=[_moneyline()], fetched_at=_DECISION, raw_tournament_id="NBA")


def _run(event=None):
    return evaluate_live_event(
        event or _event(), decision_time=_DECISION, event_resolver=_resolver(),
        sports_gateway=object(), sport_modules={"basketball": BASKETBALL_MODULE},
        coverage_check=lambda comp, season, dt: ["api_sports"])


def test_real_elo_model_evaluates_through_generic_live_path():
    res = _run()
    assert res.status is S.EVALUATED                        # chemin live complet
    assert set(res.predictions) == {"home", "away"}         # 2-way, aucune "draw"
    # Probabilités RÉELLES issues de l'Elo point-in-time (somme ≈ 1, non triviales).
    ph = res.predictions["home"].fair_probability
    assert 0.0 < ph < 1.0 and abs(ph + res.predictions["away"].fair_probability - 1.0) < 1e-9
    assert res.predictions["home"].calibration_status.value == "EXPERIMENTAL"
    # Cap BE-FR-011 : EXPERIMENTAL -> ABSTAIN (jamais BET).
    assert all(d.decision == "ABSTAIN" for d in res.decisions)


def test_point_in_time_features_use_only_prior_games():
    # La feature `as_of` == decision_time (jamais postérieure) et l'Elo dérive de
    # elo_ratings_as_of(< cutoff) — cohérent avec le walk-forward sans fuite.
    res = _run()
    fs = res.feature_set
    assert fs.as_of == _DECISION and fs.sport == "basketball"
    assert all(pf["prior_games"] >= 10 for pf in fs.participant_features.values())


def test_allstar_team_is_isolated_not_misresolved():
    # « Team LeBron » (exhibition) n'est PAS au registre -> event non résolu, jamais
    # apparié au hasard.
    res = _run(_event(slot_1="Team LeBron", slot_2="Boston Celtics"))
    assert res.status is S.EVENT_NOT_RESOLVED


def test_insufficient_history_abstains_before_season():
    # Décision AVANT le début de saison -> aucun match antérieur -> INSUFFICIENT_FEATURES
    # (aucune probabilité fabriquée).
    early = evaluate_live_event(
        _event(), decision_time=datetime(2022, 9, 1, tzinfo=timezone.utc),
        event_resolver=_resolver(), sports_gateway=object(),
        sport_modules={"basketball": BASKETBALL_MODULE},
        coverage_check=lambda comp, season, dt: ["api_sports"])
    assert early.status is S.INSUFFICIENT_FEATURES
