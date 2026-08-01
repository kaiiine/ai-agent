"""Ligues US LIVE_PRODUCT_EVALUABLE (Unité A) — MLB / NHL / NFL réellement évaluables.

Prouve, hermétiquement (fixtures embarquées + mapping compétition réel, zéro réseau) :
  - résolution DÉTERMINISTE des compétitions par roster_overlap (tid Winamax + sr id),
    jamais par le nom seul ; un tid inconnu reste UNRESOLVED ;
  - couverture d'évaluation « dataset embarqué » quand aucun provider live ne couvre la
    saison courante (sinon TOUT événement 2026 tombe en COMPETITION_NOT_COVERED) ;
  - un événement Winamax réel (nom d'équipe réel) ATTEINT son modèle -> EVALUATED ->
    ABSTAIN (EXPERIMENTAL). Plus l'opt-in réseau qui rejoue le scan live et vérifie que
    MLB/NHL/NFL ne sont plus bloqués par COMPETITION_UNRESOLVED.
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
from src.agents.quant.betting_engine.bookmakers.winamax.competition_mapping import resolve_competition
from src.agents.quant.betting_engine.live_coverage import EMBEDDED_DATASET, evaluation_coverage_check
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
    evaluate_live_event,
)
from src.agents.quant.betting_engine.sports.identity_aggregate import all_sport_teams

_DECISION = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
_START = _DECISION + timedelta(hours=6)

# sport -> (tid Winamax, canonical, home, away, template, issues)
CASES = {
    "baseball": ("25", "competition:baseball:usa:mlb", "Los Angeles Dodgers", "New York Yankees",
                 "2way", {"home", "away"}),
    "hockey": ("142", "competition:hockey:usa:nhl", "Boston Bruins", "Florida Panthers",
               "3way", {"home", "draw", "away"}),
    "american_football": ("47", "competition:american_football:usa:nfl", "Los Angeles Rams",
                          "San Francisco 49ers", "2way", {"home", "away"}),
}


# ── §3 : résolution DÉTERMINISTE par roster_overlap (jamais le nom seul) ──────────
def test_us_league_competitions_resolve_deterministically():
    assert resolve_competition("25") == ("competition:baseball:usa:mlb", "RESOLVED", "competition_table")
    assert resolve_competition("142") == ("competition:hockey:usa:nhl", "RESOLVED", "competition_table")
    assert resolve_competition("47") == ("competition:american_football:usa:nfl", "RESOLVED", "competition_table")
    assert resolve_competition("987654")[1] == "UNRESOLVED"          # inconnu -> jamais inventé


# ── Couverture model-backed : dataset embarqué quand aucun provider live ─────────
def test_embedded_coverage_only_for_validated_model_competitions():
    for canonical in (c[1] for c in CASES.values()):
        assert evaluation_coverage_check(canonical, "2026", "RESULTS") == [EMBEDDED_DATASET]
    # sport sans modèle -> aucune couverture inventée (jamais un provider fabriqué)
    assert evaluation_coverage_check("competition:cricket:ind:ipl", "2026", "RESULTS") == []


# ── Hermétique : événement réel -> modèle -> EVALUATED -> ABSTAIN ─────────────────
class _Fresh:
    effective_time, freshness_score, degraded = _DECISION - timedelta(hours=2), 0.9, False


class _Gateway:
    def data_freshness(self, competition_id, season):
        return _Fresh()


def _event(tid, home, away, template):
    sels = [RawSelection("1", home, 1.85, "slot_1")]
    if template == "3way":
        sels.append(RawSelection("x", "Nul", 3.80, "draw"))
    sels.append(RawSelection("2", away, 2.05, "slot_2"))
    label = "Résultat" if template == "3way" else "Vainqueur"
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id=f"{tid}_1", sport=None, competition="",
        slot_1_name=home, slot_2_name=away, slot_1_id=None, slot_2_id=None,
        start_time=_START, status="PREMATCH", is_outright=False,
        markets=[RawMarket(MarketType.MATCH_WINNER, 3178, label, template, False, None, sels)],
        fetched_at=_DECISION, raw_tournament_id=tid)


def _resolver():
    # Résolveur PRODUIT : identité agrégée + mapping compétition RÉEL (défaut) — jamais un stub.
    return BookmakerEventResolver(IdentityResolver(list(all_sport_teams())))


@pytest.mark.parametrize("sport", list(CASES))
def test_real_us_league_event_reaches_model_and_abstains(sport):
    tid, canonical, home, away, template, issues = CASES[sport]
    ev = _event(tid, home, away, template)
    ev = RawBookmakerEvent(**{**ev.__dict__, "sport": sport})     # sport dispatché via SPORT_MODULES
    res = evaluate_live_event(
        ev, decision_time=_DECISION, event_resolver=_resolver(), sports_gateway=_Gateway(),
        coverage_check=evaluation_coverage_check)                  # couverture model-backed
    assert res.status is S.EVALUATED                              # plus de COMPETITION_UNRESOLVED/NOT_COVERED
    assert res.canonical_event.competition_id == canonical        # compétition résolue déterministe
    assert set(res.predictions) == issues                        # 2-way OU 3-way exact
    assert all(d.decision == "ABSTAIN" for d in res.decisions)   # EXPERIMENTAL -> ABSTAIN (correct)


# ── Opt-in : scan RÉEL — MLB/NHL/NFL ne sont plus bloqués COMPETITION_UNRESOLVED ──
@pytest.mark.skipif(os.environ.get("AXON_LIVE") != "1",
                    reason="live opt-in : définir AXON_LIVE=1 (jamais en CI)")
def test_live_us_leagues_are_product_evaluable():   # pragma: no cover (réseau réel)
    from src.agents.quant.betting_engine.bookmakers.winamax.connector import WinamaxConnector
    conn = WinamaxConnector()
    resolver = _resolver()
    now = datetime.now(timezone.utc)
    ev = functools.partial(evaluate_live_event, coverage_check=evaluation_coverage_check)
    for sport in CASES:
        events = conn.scan_catalog(sport)
        statuses = Counter(r.status.value for r in
                           (ev(e, decision_time=now, event_resolver=resolver, sports_gateway=_Gateway())
                            for e in events))
        print(f"{sport}: discovered={len(events)} {dict(statuses)}")
        # Objectif Unité A : la compétition résout ET l'événement atteint le modèle. Une
        # compétition non résolue se manifesterait en EVENT_NOT_RESOLVED sans aucun EVALUATED.
        assert statuses.get("EVALUATED", 0) > 0                   # au moins un événement atteint le modèle
