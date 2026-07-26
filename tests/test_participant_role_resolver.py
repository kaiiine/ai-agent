"""Résolution slot -> rôle sportif canonique (ADR-015, §5.2bis du PRD)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.bookmakers.protocol import RawBookmakerEvent
from src.agents.quant.betting_engine.bookmakers.participant_role_resolver import (
    ParticipantRoleResolver,
    UnknownSportRoleMapping,
)


def _event(sport: str, *, is_outright: bool = False) -> RawBookmakerEvent:
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="1", sport=sport,
        competition="X", slot_1_name="A", slot_2_name="B",
        slot_1_id="10", slot_2_id="20",
        start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
        status="PREMATCH", is_outright=is_outright, markets=[],
        fetched_at=datetime.now(timezone.utc),
    )


def test_football_slots_map_to_home_away():
    parts = ParticipantRoleResolver().resolve(_event("football"))
    assert [(p.role, p.name, p.bookmaker_slot) for p in parts] == [
        ("home", "A", "slot_1"),
        ("away", "B", "slot_2"),
    ]


def test_tennis_slots_map_to_players_never_home_away():
    parts = ParticipantRoleResolver().resolve(_event("tennis"))
    roles = [p.role for p in parts]
    assert roles == ["player_a", "player_b"]
    assert "home" not in roles and "away" not in roles


def test_slot_is_preserved_for_audit_but_distinct_from_role():
    # §5.2bis : le slot brut reste consultable, mais n'est pas le rôle.
    parts = ParticipantRoleResolver().resolve(_event("football"))
    assert parts[0].bookmaker_slot == "slot_1" and parts[0].role == "home"
    assert parts[0].bookmaker_slot != parts[0].role


def test_unknown_sport_fails_loud_never_defaults_to_home():
    with pytest.raises(UnknownSportRoleMapping):
        ParticipantRoleResolver().resolve(_event("handball"))


def test_outright_has_no_opposing_participants():
    assert ParticipantRoleResolver().resolve(_event("football", is_outright=True)) == []
