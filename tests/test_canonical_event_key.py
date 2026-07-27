"""build_canonical_event_key — testée seule, hors des objets qui l'utilisent."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from src.agents.quant.betting_engine.bookmakers.canonical_event import (
    build_canonical_event_key,
)

_KO = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)
_LIGUE1 = "competition:football:fra:ligue1"


def test_key_is_deterministic_and_bookmaker_order_independent():
    a = build_canonical_event_key(
        "football", _LIGUE1, _KO,
        [("home", "team:football:fra:psg"), ("away", "team:football:fra:marseille")],
    )
    # mêmes participants+rôles, ordre d'entrée inversé -> MÊME clé
    b = build_canonical_event_key(
        "football", _LIGUE1, _KO,
        [("away", "team:football:fra:marseille"), ("home", "team:football:fra:psg")],
    )
    assert a == b


def test_key_preserves_role_information():
    key = build_canonical_event_key(
        "football", _LIGUE1, _KO,
        [("home", "team:football:fra:psg"), ("away", "team:football:fra:marseille")],
    )
    assert "home=psg" in key
    assert "away=marseille" in key
    assert key.startswith("event:football:ligue1:2026-08-01T18:00:00Z:")


def test_swapping_which_team_is_home_changes_the_key():
    # L'info de rôle compte : PSG à domicile != Marseille à domicile.
    psg_home = build_canonical_event_key(
        "football", _LIGUE1, _KO,
        [("home", "team:football:fra:psg"), ("away", "team:football:fra:marseille")],
    )
    om_home = build_canonical_event_key(
        "football", _LIGUE1, _KO,
        [("home", "team:football:fra:marseille"), ("away", "team:football:fra:psg")],
    )
    assert psg_home != om_home


def test_scheduled_at_is_normalized_to_utc():
    paris = timezone(timedelta(hours=2))
    local = datetime(2026, 8, 1, 20, 0, tzinfo=paris)   # 20:00 +02:00 == 18:00Z
    key = build_canonical_event_key(
        "football", _LIGUE1, local,
        [("home", "team:football:fra:psg"), ("away", "team:football:fra:marseille")],
    )
    assert "2026-08-01T18:00:00Z" in key


def test_naive_datetime_is_rejected_not_guessed():
    with pytest.raises(ValueError):
        build_canonical_event_key(
            "football", _LIGUE1, datetime(2026, 8, 1, 18, 0),  # sans tzinfo
            [("home", "team:football:fra:psg"), ("away", "team:football:fra:marseille")],
        )


def test_tennis_uses_player_roles_not_home_away():
    key = build_canonical_event_key(
        "tennis", "competition:tennis:wta:hamburg", _KO,
        [("player_a", "team:tennis:wta:bondar"), ("player_b", "team:tennis:wta:korpatsch")],
    )
    assert "player_a=bondar" in key and "player_b=korpatsch" in key
    assert "home" not in key and "away" not in key
