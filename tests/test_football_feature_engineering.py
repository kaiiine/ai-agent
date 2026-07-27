"""feature_engineering football V0 : CanonicalEvent -> EventFeatureSet.

Hermétique : gateway factice injecté (formes/classement en dur), aucun réseau.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.gateway.core.errors import NoDataAvailableError
from src.agents.quant.betting_engine.core.canonical_event import (
    CanonicalEvent,
    CanonicalParticipant,
)
from src.agents.quant.betting_engine.sports.football.feature_engineering import (
    build_event_feature_set,
)

_KO = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)
_PSG = "team:football:fra:psg"
_OM = "team:football:fra:marseille"


class _FakeGateway:
    def __init__(self, forms: dict[str, list[dict]], standings: dict[str, float]):
        self._forms = forms
        self._standings = standings

    def recent_form(self, canonical_team_id, last, season):
        if canonical_team_id not in self._forms:
            raise NoDataAvailableError(canonical_team_id)
        return self._forms[canonical_team_id][:last]

    def standings_strength(self, league_canonical_id, season):
        return dict(self._standings)


def _m(day: str, is_home: bool, gh: int, ga: int) -> dict:
    return {"date": day, "opponent_id": "x", "goals_home": gh, "goals_away": ga,
            "is_home": is_home, "league_id": "competition:football:fra:ligue1", "season": "2026"}


def _event(parts=None, when=_KO) -> CanonicalEvent:
    parts = parts or (CanonicalParticipant(_PSG, "home"), CanonicalParticipant(_OM, "away"))
    return CanonicalEvent(
        event_id="event:football:ligue1:2026-08-01T18:00:00Z:away=marseille|home=psg",
        sport="football", competition_id="competition:football:fra:ligue1",
        participants=parts, scheduled_at=when,
    )


def _five_home_wins():   # 5x victoire 2-0 à domicile, plus récente en premier
    return [_m(d, True, 2, 0) for d in
            ["2026-07-28", "2026-07-25", "2026-07-21", "2026-07-18", "2026-07-14"]]


def _five_away_losses():  # 5x défaite 0-1 à l'extérieur
    return [_m(d, False, 1, 0) for d in
            ["2026-07-28", "2026-07-25", "2026-07-21", "2026-07-18", "2026-07-14"]]


def test_fully_resolved_event_has_features_and_no_missing():
    gw = _FakeGateway({_PSG: _five_home_wins(), _OM: _five_away_losses()},
                      {_PSG: 1.3, _OM: 0.7})
    fs = build_event_feature_set(_event(), gateway=gw, as_of=_KO)

    assert fs.sport == "football" and fs.as_of == _KO
    assert fs.feature_set_version == "football-1.0"
    assert fs.event_features == {}
    assert fs.missing_features == set()

    psg = fs.participant_features[_PSG]
    assert psg["form_matches"] == 5
    assert psg["form_points_per_game"] == 3.0
    assert psg["form_goals_for_avg"] == 2.0
    assert psg["form_goal_diff_avg"] == 2.0
    assert psg["standings_strength"] == 1.3
    assert psg["rest_days"] == 4                      # 2026-07-28 -> 2026-08-01

    assert fs.matchup_features["strength_differential"] == 0.6     # 1.3 - 0.7
    assert fs.matchup_features["form_ppg_differential"] == 3.0      # 3.0 - 0.0
    assert fs.matchup_features["form_goal_diff_differential"] == 3.0  # 2.0 - (-1.0)


def test_form_stats_exact_arithmetic():
    gw = _FakeGateway(
        {_PSG: [_m("2026-07-30", True, 2, 0), _m("2026-07-27", False, 1, 0)],
         _OM: _five_away_losses()},
        {_PSG: 1.2, _OM: 0.8},
    )
    psg = build_event_feature_set(_event(), gateway=gw, as_of=_KO).participant_features[_PSG]
    assert psg["form_matches"] == 2
    assert psg["form_points_per_game"] == 1.5        # (3*1 + 0) / 2
    assert psg["form_goals_for_avg"] == 1.0          # (2 + 0) / 2
    assert psg["form_goals_against_avg"] == 0.5      # (0 + 1) / 2
    assert psg["form_goal_diff_avg"] == 0.5
    assert psg["form_win_rate"] == 0.5


def test_no_form_is_recorded_missing_never_crashes():
    gw = _FakeGateway({_OM: _five_away_losses()}, {_PSG: 1.3, _OM: 0.7})  # PSG absent
    fs = build_event_feature_set(_event(), gateway=gw, as_of=_KO)
    assert f"form:{_PSG}" in fs.missing_features
    assert f"rest_days:{_PSG}" in fs.missing_features
    assert "form_points_per_game" not in fs.participant_features[_PSG]
    # standings de PSG existe quand même -> pas dans missing
    assert f"standings:{_PSG}" not in fs.missing_features
    assert fs.participant_features[_PSG]["standings_strength"] == 1.3


def test_insufficient_form_is_flagged_but_still_computed():
    gw = _FakeGateway(
        {_PSG: [_m("2026-07-30", True, 1, 0), _m("2026-07-27", True, 2, 1)],
         _OM: _five_away_losses()},
        {_PSG: 1.3, _OM: 0.7},
    )
    fs = build_event_feature_set(_event(), gateway=gw, as_of=_KO)
    assert f"form_insufficient:{_PSG}" in fs.missing_features   # < 5 matchs
    assert fs.participant_features[_PSG]["form_matches"] == 2    # mais calculé


def test_missing_standings_recorded_and_matchup_degrades():
    gw = _FakeGateway({_PSG: _five_home_wins(), _OM: _five_away_losses()},
                      {_PSG: 1.3})                                # OM absent du classement
    fs = build_event_feature_set(_event(), gateway=gw, as_of=_KO)
    assert f"standings:{_OM}" in fs.missing_features
    # strength_differential ne peut pas être calculé -> absent, mais les diffs de forme oui
    assert "strength_differential" not in fs.matchup_features
    assert "form_ppg_differential" in fs.matchup_features


def test_deterministic_same_inputs_same_output():
    gw = _FakeGateway({_PSG: _five_home_wins(), _OM: _five_away_losses()},
                      {_PSG: 1.3, _OM: 0.7})
    assert build_event_feature_set(_event(), gateway=gw, as_of=_KO) == build_event_feature_set(_event(), gateway=gw, as_of=_KO)


def test_season_derived_from_kickoff():
    # janvier 2026 -> saison "2025" (mois < 7)
    gw = _FakeGateway({_PSG: _five_home_wins(), _OM: _five_away_losses()}, {_PSG: 1.3, _OM: 0.7})
    captured = {}
    orig = gw.recent_form

    def spy(cid, last, season):
        captured["season"] = season
        return orig(cid, last, season)

    gw.recent_form = spy
    build_event_feature_set(
        _event(when=datetime(2026, 1, 15, tzinfo=timezone.utc)), gateway=gw,
        as_of=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    assert captured["season"] == "2025"


def test_dixon_coles_strengths_emitted_when_form_present():
    gw = _FakeGateway({_PSG: _five_home_wins(), _OM: _five_away_losses()},
                      {_PSG: 1.3, _OM: 0.7})
    fs = build_event_feature_set(_event(), gateway=gw, as_of=_KO)
    for cid in (_PSG, _OM):
        assert "attack_strength" in fs.participant_features[cid]
        assert "defense_strength" in fs.participant_features[cid]


def test_no_strengths_when_form_absent():
    gw = _FakeGateway({_OM: _five_away_losses()}, {_PSG: 1.3, _OM: 0.7})  # PSG sans forme
    fs = build_event_feature_set(_event(), gateway=gw, as_of=_KO)
    assert "attack_strength" not in fs.participant_features[_PSG]
    assert f"form:{_PSG}" in fs.missing_features
