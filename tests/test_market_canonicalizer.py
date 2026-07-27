"""Canonicalisation atomique marché -> OddsSnapshot + anti-régression slot≠role.

Synthétique/schéma-fidèle (mécanique + garde-fous). Le test d'intégration sur un
PAYLOAD WINAMAX RÉEL figé sera ajouté à réception de la capture désensibilisée.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness, MarketPrediction, PredictionExplanation, UncertaintyStatus,
)
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventMapping
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.bookmakers.market_canonicalizer import (
    MarketCanonicalizationStatus as St,
    ParticipantRoleResolution,
    build_market_id,
    canonicalize_market,
    resolve_participant_roles,
)
from src.agents.quant.betting_engine.value_engine.market_coherence import validate_market

_T = datetime(2025, 8, 1, 17, tzinfo=timezone.utc)
_CANON = "event:football:fra:ligue1:2025-08-01T17:00:00Z:away=psg|home=marseille"


def _sel(canon, odds):
    return RawSelection(code="?", label="?", decimal_odds=odds, canonical_selection=canon)


def _1x2(slot1_odds=1.75, draw_odds=3.4, slot2_odds=4.20):
    return [_sel("slot_1", slot1_odds), _sel("draw", draw_odds), _sel("slot_2", slot2_odds)]


def _market(selections=None, market_type=MarketType.MATCH_WINNER, template="3way"):
    return RawMarket(market_type=market_type, raw_bet_type=3178, raw_label="Résultat",
                     template=template, is_live=False, special_bet_value="type=prematch",
                     selections=selections if selections is not None else _1x2())


def _event(market, bem_id="E1"):
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id=bem_id, sport="football", competition="Ligue 1",
        slot_1_name="Marseille", slot_2_name="PSG", slot_1_id="1", slot_2_id="2",
        start_time=_T, status="PREMATCH", is_outright=False, markets=[market], fetched_at=_T,
    )


def _mapping(bem_id="E1", identity="RESOLVED", eligibility="ELIGIBLE"):
    return BookmakerEventMapping(
        bookmaker="winamax", bookmaker_event_id=bem_id, sport="football",
        canonical_event_id=_CANON if identity == "RESOLVED" else None,
        competition_id="competition:football:fra:ligue1",
        identity_status=identity, eligibility_status=eligibility, evidence=(), confirmed_at=_T,
    )


def _roles(bem_id="E1", slot_1="home", slot_2="away"):
    return ParticipantRoleResolution(bem_id, {"slot_1": slot_1, "slot_2": slot_2})


def _canon(market, mapping=None, roles=None):
    ev = _event(market)
    return canonicalize_market(ev, market, mapping or _mapping(), roles or _roles())


# ── La cote suit le rôle résolu (cœur anti-régression) ────────────────────────
def test_bookmaker_order_matches_roles():
    res = _canon(_market(_1x2(slot1_odds=1.75, slot2_odds=4.20)), roles=_roles(slot_1="home", slot_2="away"))
    assert res.is_ok
    by_sel = {s.selection: s.decimal_odds for s in res.snapshots}
    assert by_sel == {"home": 1.75, "draw": 3.4, "away": 4.20}


def test_reversed_bookmaker_order_odds_follow_role():
    # slot_1 = visiteur (4.20), slot_2 = domicile (1.75) ; resolver : slot_1->away, slot_2->home.
    # La cote doit SUIVRE le rôle, pas la position -> échoue si slot_1==home réintroduit.
    res = _canon(_market(_1x2(slot1_odds=4.20, slot2_odds=1.75)), roles=_roles(slot_1="away", slot_2="home"))
    assert res.is_ok
    by_sel = {s.selection: s.decimal_odds for s in res.snapshots}
    assert by_sel["away"] == 4.20     # slot_1 (4.20) -> away
    assert by_sel["home"] == 1.75     # slot_2 (1.75) -> home
    assert by_sel["draw"] == 3.4


def test_draw_is_unchanged():
    res = _canon(_market())
    assert {s.selection for s in res.snapshots} == {"home", "draw", "away"}


def test_real_participant_role_resolver_football_slot1_is_home():
    # Chemin réaliste : la SEULE autorité (ParticipantRoleResolver) est consommée.
    market = _market(_1x2(slot1_odds=1.75, slot2_odds=4.20))
    ev = _event(market)
    resolution = resolve_participant_roles(ev)              # football -> slot_1=home (ADR-015)
    res = canonicalize_market(ev, market, _mapping(), resolution)
    by_sel = {s.selection: s.decimal_odds for s in res.snapshots}
    assert by_sel["home"] == 1.75 and by_sel["away"] == 4.20


# ── Atomicité + métadonnées + market_id + cohérence ───────────────────────────
def test_atomic_three_snapshots():
    res = _canon(_market())
    assert len(res.snapshots) == 3


def test_snapshots_share_market_metadata():
    res = _canon(_market())
    assert len({s.bookmaker for s in res.snapshots}) == 1
    assert len({s.event_id for s in res.snapshots}) == 1
    assert len({s.market_type for s in res.snapshots}) == 1
    assert len({s.observed_at for s in res.snapshots}) == 1     # même scan -> même observed_at


def test_market_id_deterministic_and_on_result():
    assert build_market_id("winamax", _CANON, "MATCH_WINNER") == f"winamax:{_CANON}:MATCH_WINNER"
    res = _canon(_market())
    assert res.market_id == f"winamax:{_CANON}:MATCH_WINNER"


def test_produced_market_passes_market_coherence():
    res = _canon(_market())
    prediction = MarketPrediction(
        "football", "MATCH_WINNER", "home", 0.5, 0.5, 0.5, UncertaintyStatus.NOT_ESTIMATED,
        "m.v0", 1.0, DataReadiness.EXPERIMENTAL, _T, PredictionExplanation([], set(), [], []),
    )
    validate_market(res.snapshots, prediction)                  # ne lève pas


# ── Identité ≠ éligibilité (distinction demandée) ─────────────────────────────
def test_event_not_resolved():
    res = _canon(_market(), mapping=_mapping(identity="AMBIGUOUS"))
    assert res.status is St.EVENT_NOT_RESOLVED
    assert res.snapshots == ()


def test_resolved_but_not_eligible_is_distinct_from_not_resolved():
    # RESOLVED mais eligibility != ELIGIBLE -> EVENT_NOT_ELIGIBLE, JAMAIS "non résolu".
    res = _canon(_market(), mapping=_mapping(identity="RESOLVED", eligibility="UNSUPPORTED_EVENT_TYPE"))
    assert res.status is St.EVENT_NOT_ELIGIBLE
    assert res.status is not St.EVENT_NOT_RESOLVED
    assert res.canonical_event_id == _CANON                     # bien résolu, juste inéligible
    assert res.snapshots == ()


# ── Marché hors scope ─────────────────────────────────────────────────────────
def test_outright_is_unsupported():
    res = _canon(_market(market_type=MarketType.OUTRIGHT_WINNER, template="ListOdd"))
    assert res.status is St.UNSUPPORTED_MARKET


def test_two_way_without_draw_is_unsupported():
    res = _canon(_market(selections=[_sel("slot_1", 1.8), _sel("slot_2", 2.0)], template="2way"))
    assert res.status is St.UNSUPPORTED_MARKET


# ── Données invalides ─────────────────────────────────────────────────────────
def test_missing_draw_is_invalid():
    res = _canon(_market(selections=[_sel("slot_1", 1.8), _sel("slot_2", 2.0)]))   # template 3way mais 2 issues
    assert res.status is St.INVALID_MARKET_DATA


def test_duplicate_slot_is_invalid():
    res = _canon(_market(selections=[_sel("slot_1", 1.8), _sel("slot_1", 1.9), _sel("draw", 3.4)]))
    assert res.status is St.INVALID_MARKET_DATA


def test_invalid_odds_is_invalid():
    res = _canon(_market(_1x2(slot1_odds=1.0)))
    assert res.status is St.INVALID_MARKET_DATA


def test_incomplete_role_resolution_is_invalid():
    res = _canon(_market(), roles=ParticipantRoleResolution("E1", {"slot_1": "home"}))  # slot_2 absent
    assert res.status is St.INVALID_MARKET_DATA
    assert "slot_2" in res.details.get("slots_manquants", [])


# ── Assemblages incohérents ───────────────────────────────────────────────────
def test_mismatched_events_rejected():
    market = _market()
    ev = _event(market, bem_id="E1")
    res = canonicalize_market(ev, market, _mapping(bem_id="E2"), _roles(bem_id="E1"))
    assert res.status is St.INVALID_MARKET_DATA
    assert "événements différents" in res.reason


def test_market_not_part_of_event_rejected():
    ev = _event(_market())
    stray = _market()                                          # autre objet marché
    res = canonicalize_market(ev, stray, _mapping(), _roles())
    assert res.status is St.INVALID_MARKET_DATA


# ── Contexte structuré sur échec (jamais de skip silencieux) ──────────────────
def test_failure_result_carries_structured_context():
    res = _canon(_market(), mapping=_mapping(identity="CONFLICT"))
    assert res.status is St.EVENT_NOT_RESOLVED
    assert res.reason
    assert res.bookmaker_event_id == "E1"
    assert res.details.get("identity_status") == "CONFLICT"
