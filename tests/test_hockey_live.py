"""Hockey LIVE 3-way câblé (finalization §1/§2) — le vrai modèle Davidson traverse le
chemin live générique AVEC fraîcheur MESURÉE. Hermétique (fixture réelle, zéro réseau).

Prouve : marché réglementaire 3-way (H/D/A), Elo+Davidson point-in-time, freshness
Gateway->BE mesurée (retire le blocker measurable_live_freshness), EXPERIMENTAL -> ABSTAIN,
ordre d'issues invariant, équipe hors-roster isolée.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
    evaluate_live_event,
)
from src.agents.quant.betting_engine.sports.hockey.live_model import HOCKEY_MODULE, NHL_TEAMS

_DECISION = datetime(2023, 3, 1, 12, tzinfo=timezone.utc)      # mi-saison : historique suffisant
_FACEOFF = datetime(2023, 3, 2, 0, tzinfo=timezone.utc)


class _Freshness:
    def __init__(self, effective_time, score=0.9, degraded=False):
        self.effective_time, self.freshness_score, self.degraded = effective_time, score, degraded


class _Gateway:
    """Gateway qui EXPOSE une fraîcheur mesurée (Gateway mesure -> BE lit)."""
    def data_freshness(self, competition_id, season):
        return _Freshness(_DECISION - timedelta(hours=2))       # récent -> non stale, mesuré


def _resolver():
    comp = lambda ev: (("competition:hockey:usa:nhl", "RESOLVED", "competition_table")
                        if ev.raw_tournament_id == "NHL" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(IdentityResolver(NHL_TEAMS), competition_resolver=comp)


def _market(reverse=False):
    sels = [RawSelection("1", "Boston Bruins", 2.10, "slot_1"),
            RawSelection("x", "Nul", 3.80, "draw"),
            RawSelection("2", "Toronto Maple Leafs", 2.60, "slot_2")]
    if reverse:
        sels = list(reversed(sels))
    return RawMarket(MarketType.MATCH_WINNER, 3178, "Résultat", "3way", False, None, sels)


def _event(reverse=False, s1="Boston Bruins", s2="Toronto Maple Leafs"):
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="NHL_BOS_TOR", sport="hockey", competition="NHL",
        slot_1_name=s1, slot_2_name=s2, slot_1_id="1", slot_2_id="2",
        start_time=_FACEOFF, status="PREMATCH", is_outright=False,
        markets=[_market(reverse=reverse)], fetched_at=_DECISION, raw_tournament_id="NHL")


def _run(event=None):
    return evaluate_live_event(
        event or _event(), decision_time=_DECISION, event_resolver=_resolver(),
        sports_gateway=_Gateway(), sport_modules={"hockey": HOCKEY_MODULE},
        coverage_check=lambda comp, season, dt: ["api_sports"])


def test_regulation_three_way_flows_through_live_with_measured_freshness():
    res = _run()
    assert res.status is S.EVALUATED
    assert set(res.predictions) == {"home", "draw", "away"}     # 3-way réglementaire
    ph = {s: res.predictions[s].fair_probability for s in ("home", "draw", "away")}
    assert abs(sum(ph.values()) - 1.0) < 1e-9 and ph["draw"] > 0.0
    assert res.predictions["home"].calibration_status.value == "EXPERIMENTAL"
    assert all(d.decision == "ABSTAIN" for d in res.decisions)  # cap BE-FR-011
    # Le blocker measurable_live_freshness est retiré : la Gateway a exposé une fraîcheur.
    assert res.freshness_score == 0.9


def test_selection_order_invariant():
    a = {d.selection: (d.model_probability, d.decision) for d in _run(_event()).decisions}
    b = {d.selection: (d.model_probability, d.decision) for d in _run(_event(reverse=True)).decisions}
    assert a == b


def test_non_nhl_team_isolated():
    res = _run(_event(s1="Paris Saint-Germain"))                 # hors roster NHL
    assert res.status is S.EVENT_NOT_RESOLVED
