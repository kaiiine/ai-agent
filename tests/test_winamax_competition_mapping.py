"""Table tournoi Winamax -> compétition canonique (discipline de vérification)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.bookmakers.winamax.competition_mapping import (
    WinamaxCompetitionMapping,
    resolve_competition,
)


def test_verified_mapping_resolves():
    cid, status, method = resolve_competition("4")           # Ligue 1
    assert cid == "competition:football:fra:ligue1"
    assert status == "RESOLVED"
    assert method == "competition_table"


def test_premier_league_resolves():
    cid, status, _ = resolve_competition("1")
    assert cid == "competition:football:eng:premier_league"
    assert status == "RESOLVED"


def test_unknown_tournament_is_unresolved():
    assert resolve_competition("999999") == (None, "UNRESOLVED", "none")
    assert resolve_competition(None) == (None, "UNRESOLVED", "none")


def test_serie_a_resolves_after_onboarding():
    # Serie A (tid 33) : équipes peuplées (IDs football_data_org vérifiés en direct)
    # + mapping vérifié (live_call) -> désormais RÉSOLUE (onboarding 2026-07-31).
    cid, status, _ = resolve_competition("33")
    assert cid == "competition:football:ita:serie_a"
    assert status == "RESOLVED"


def test_unverified_mapping_is_never_served(monkeypatch):
    # Invariant GW-FR-005 (indépendant du seed) : une entrée NON vérifiée n'est
    # JAMAIS servie. On l'exerce en injectant une entrée unverified dans la table.
    import src.agents.quant.betting_engine.bookmakers.winamax.competition_mapping as cm
    entry = WinamaxCompetitionMapping("77777", "competition:football:fra:ligue1", None, "unverified")
    monkeypatch.setitem(cm._BY_TID, "77777", entry)
    assert resolve_competition("77777") == (None, "UNRESOLVED", "unverified")


def test_is_verified_property():
    verified = WinamaxCompetitionMapping(
        "4", "competition:football:fra:ligue1",
        datetime(2026, 7, 26, tzinfo=timezone.utc), "snapshot",
    )
    unverified = WinamaxCompetitionMapping("33", "competition:football:ita:serie_a", None, "unverified")
    assert verified.is_verified is True
    assert unverified.is_verified is False


def test_invalid_verification_method_rejected():
    with pytest.raises(ValueError):
        WinamaxCompetitionMapping(
            "4", "competition:football:fra:ligue1",
            datetime(2026, 7, 26, tzinfo=timezone.utc), "vibes",
        )
