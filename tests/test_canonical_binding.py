"""Pont événement bookmaker résolu -> CanonicalEvent (canonical_binding)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver
from src.agents.quant.betting_engine.bookmakers.protocol import RawBookmakerEvent
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.canonical_binding import build_canonical_event

_KO = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)


def _registry() -> BookmakerEventResolver:
    identity = IdentityResolver([
        CanonicalEntity("team:football:fra:psg", "Paris Saint Germain",
                        ["PSG", "Paris SG", "Paris Saint-Germain"], {}),
        CanonicalEntity("team:football:fra:marseille", "Marseille", ["OM"], {}),
    ])
    comp = lambda ev: (("competition:football:fra:ligue1", "RESOLVED", "competition_table")
                        if ev.raw_tournament_id == "4" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _raw(**kw) -> RawBookmakerEvent:
    base = dict(
        bookmaker="winamax", bookmaker_event_id="E1", sport="football",
        competition="Ligue 1", slot_1_name="Paris Saint-Germain", slot_2_name="Marseille",
        slot_1_id=None, slot_2_id=None, start_time=_KO, status="PREMATCH",
        is_outright=False, markets=[], fetched_at=_KO, raw_tournament_id="4",
    )
    base.update(kw)
    return RawBookmakerEvent(**base)


def test_resolved_event_builds_canonical_event_with_roles():
    reg = _registry()
    raw = _raw()
    mapping = reg.resolve_event(raw)
    assert mapping.is_usable

    event = build_canonical_event(raw, mapping)
    assert event is not None
    assert event.event_id == mapping.canonical_event_id
    assert event.competition_id == "competition:football:fra:ligue1"
    assert event.scheduled_at == _KO
    # slot_1 (PSG) -> home, slot_2 (OM) -> away : identité (registry) + rôle (ADR-015)
    by_role = {p.role: p.canonical_id for p in event.participants}
    assert by_role == {
        "home": "team:football:fra:psg",
        "away": "team:football:fra:marseille",
    }


def test_unusable_mapping_yields_none():
    reg = _registry()
    raw = _raw(slot_1_name="Copenhague")           # inconnu -> UNRESOLVED -> non usable
    mapping = reg.resolve_event(raw)
    assert not mapping.is_usable
    assert build_canonical_event(raw, mapping) is None
