"""Scan produit MULTISPORT (§3/§4) — les 6 modèles sont RÉELLEMENT atteignables depuis
le chemin produit (`axon recommend` -> multisport_events -> resolver agrégé -> SPORT_MODULES
-> evaluate_live_batch -> adaptateur), pas seulement via des seams de test.

Hermétique : prouve que le scan agrège les 6 sports, que chacun est ÉVALUÉ ou REJETÉ avec
un statut typé (jamais un arrêt sur le premier non résolu), et que l'adaptateur Advisor
gère 2-way ET 3-way (un marché 2-way ne casse plus sur un « draw » inexistant).

Opt-in (`AXON_LIVE=1`) : scan RÉEL des 6 sports, funnel par sport, SOURCE_LIVE exigé,
aucun fallback fixture.
"""

from __future__ import annotations

import functools
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.bookmakers.winamax.catalogue import multisport_events
from src.agents.quant.betting_engine.live_batch import evaluate_live_batch
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
    evaluate_live_event,
)
from src.agents.quant.betting_engine.sports.identity_aggregate import all_sport_teams
from src.agents.quant.advisor.input_adapter.betting_engine_adapter import adapt_live_batch

# 2023-03-01 : fenêtre où basket/baseball/NFL/volley/hockey ont un historique suffisant.
# Football (FL1 2025-26) n'a PAS encore de matchs -> rejet typé (prouve l'isolation).
_DECISION = datetime(2023, 3, 1, 12, tzinfo=timezone.utc)
_FACEOFF = _DECISION + timedelta(days=1)

# sport -> (tournamentId, home, away, template, canonical, issues attendues)
CASES = {
    "football": ("L1", "Paris Saint Germain", "Lens", "3way",
                 "competition:football:fra:ligue1", {"home", "draw", "away"}),
    "basketball": ("NBA", "Boston Celtics", "Los Angeles Lakers", "2way",
                   "competition:basketball:usa:nba", {"home", "away"}),
    "baseball": ("MLB", "Boston Red Sox", "Minnesota Twins", "2way",
                 "competition:baseball:usa:mlb", {"home", "away"}),
    "american_football": ("NFL", "Las Vegas Raiders", "Cincinnati Bengals", "2way",
                          "competition:american_football:usa:nfl", {"home", "away"}),
    "volleyball": ("VOL", "Vero Volley W", "Bergamo W", "2way",
                   "competition:volleyball:ita:serie_a1", {"home", "away"}),
    "hockey": ("NHL", "Boston Bruins", "Toronto Maple Leafs", "3way",
               "competition:hockey:usa:nhl", {"home", "draw", "away"}),
}
_EVALUABLE = {"basketball", "baseball", "american_football", "volleyball", "hockey"}


class _Freshness:
    def __init__(self, t):
        self.effective_time, self.freshness_score, self.degraded = t, 0.9, False


class _Gateway:
    def data_freshness(self, competition_id, season):
        return _Freshness(_DECISION - timedelta(hours=2))


class _Connector:
    """Connecteur hermétique : scan_catalog(sport) -> les événements pré-bâtis du sport."""
    def __init__(self, by_sport):
        self._by_sport = by_sport

    def scan_catalog(self, sport):
        return list(self._by_sport.get(sport, []))


def _event(sport, tid, s1, s2, template, *, eid=None):
    sels = [RawSelection("1", s1, 1.80, "slot_1")]
    if template == "3way":
        sels.append(RawSelection("x", "Nul", 3.60, "draw"))
    sels.append(RawSelection("2", s2, 2.10, "slot_2"))
    label = "Résultat" if template == "3way" else "Vainqueur"
    market = RawMarket(MarketType.MATCH_WINNER, 3178, label, template, False, None, sels)
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id=eid or f"{sport}_1", sport=sport, competition=tid,
        slot_1_name=s1, slot_2_name=s2, slot_1_id="1", slot_2_id="2",
        start_time=_FACEOFF, status="PREMATCH", is_outright=False,
        markets=[market], fetched_at=_DECISION, raw_tournament_id=tid)


def _comp_resolver(tid):
    for _sport, (t, _h, _a, _tpl, canon, _sel) in CASES.items():
        if t == tid:
            return (canon, "RESOLVED", "competition_table")
    return (None, "UNRESOLVED", "none")


def _resolver():
    return BookmakerEventResolver(IdentityResolver(list(all_sport_teams())),
                                  competition_resolver=_comp_resolver)


def _batch(by_sport, sports):
    evaluate = functools.partial(evaluate_live_event, coverage_check=lambda *a: ["api_sports"])
    return evaluate_live_batch(
        _Connector(by_sport), sports_gateway=_Gateway(), event_resolver=_resolver(),
        catalogue=lambda conn: multisport_events(conn, sports),
        evaluate=evaluate, now_fn=lambda: _DECISION)


# ── multisport_events agrège TOUS les sports demandés ────────────────────────────
def test_multisport_events_aggregates_every_requested_sport():
    by_sport = {s: [_event(s, *CASES[s][:4])] for s in CASES}
    events = multisport_events(_Connector(by_sport), list(CASES))
    assert Counter(e.sport for e in events) == {s: 1 for s in CASES}   # aucun sport perdu


# ── Le scan atteint les 6, isole les non-évaluables, n'arrête jamais le run ───────
def test_six_sport_batch_reaches_all_and_isolates_unevaluable():
    by_sport = {s: [_event(s, *CASES[s][:4])] for s in CASES}
    batch = _batch(by_sport, list(CASES))
    by_sport_res = {raw.sport: res for raw, res in batch.results}

    assert len(batch.results) == 6                       # les 6 présents (scan non interrompu)
    for sport in _EVALUABLE:
        res = by_sport_res[sport]
        assert res.status is S.EVALUATED, f"{sport}: {res.status} {res.reason}"
        assert set(res.predictions) == CASES[sport][5]   # issues 2-way OU 3-way exactes
        assert all(d.decision == "ABSTAIN" for d in res.decisions)   # EXPERIMENTAL -> ABSTAIN
    # Football (mauvaise ère) : rejet TYPÉ, jamais un crash ni un arrêt du run.
    assert isinstance(by_sport_res["football"].status, S)
    assert by_sport_res["football"].status is not S.EVALUATED


def test_scan_does_not_stop_on_first_unresolved_event():
    # Un événement non résolu placé EN PREMIER ne doit pas empêcher les suivants.
    by_sport = {s: [_event(s, *CASES[s][:4])] for s in CASES}
    by_sport["basketball"] = [
        _event("basketball", "NBA", "Team LeBron", "Team Durant", "2way", eid="allstar"),  # hors roster
        by_sport["basketball"][0],
    ]
    batch = _batch(by_sport, list(CASES))
    res = {(raw.sport, raw.bookmaker_event_id): r for raw, r in batch.results}
    assert res[("basketball", "allstar")].status is S.EVENT_NOT_RESOLVED   # isolé
    assert res[("basketball", "basketball_1")].status is S.EVALUATED       # le suivant passe


# ── L'adaptateur Advisor gère 2-way ET 3-way (schéma-driven) ─────────────────────
def test_adapter_handles_two_way_and_three_way_end_to_end():
    by_sport = {s: [_event(s, *CASES[s][:4])] for s in _EVALUABLE}
    batch = _batch(by_sport, list(_EVALUABLE))
    adapted = adapt_live_batch(batch)                    # ne DOIT PAS crasher sur un « draw » 2-way
    per_sport = Counter(e.sport for e in adapted.evaluations)
    assert per_sport["basketball"] == 2 and per_sport["baseball"] == 2       # 2-way -> 2 sélections
    assert per_sport["american_football"] == 2 and per_sport["volleyball"] == 2
    assert per_sport["hockey"] == 3                                          # 3-way -> 3 sélections
    assert adapted.skipped == ()                                            # tous EVALUATED, aucun skip


# ── Opt-in : scan RÉEL multisport, funnel par sport, SOURCE_LIVE, zéro fixture ────
@pytest.mark.skipif(os.environ.get("AXON_LIVE") != "1",
                    reason="live opt-in : définir AXON_LIVE=1 (jamais en CI)")
def test_live_product_multisport_source_live():   # pragma: no cover (réseau réel)
    from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import (
        SOURCE_LIVE, capture_live_state, replay,
    )
    from src.agents.quant.betting_engine.capability import coverage_matrix

    for sport in CASES:
        capture = capture_live_state(sport)              # VRAI réseau, lève si échec (aucun fallback)
        assert capture.source == SOURCE_LIVE
        events = list(replay(capture))
        if not events:
            print(f"{sport}: NO_LIVE_EVENTS")            # absent aujourd'hui, mais enregistré/testable
            continue
        m = coverage_matrix(events, sport)
        print(f"{sport}: discovered={m.events_discovered} model_capable={m.competitions_model_capable} "
              f"data_capable={m.competitions_data_capable} evaluable={m.events_evaluable} "
              f"reasons={m.by_reason}")
        assert m.events_discovered >= m.events_evaluable  # découverte >= évaluable (honnête)
