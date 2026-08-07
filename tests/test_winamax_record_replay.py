"""Winamax record/replay + fidélité de la transformation payload -> événement canonique.

État de test SYNTHÉTIQUE mais fidèle à la structure réelle (tournamentId 4 = Ligue 1,
bet « Résultat »/3way, outcomes 1/x/2), JAMAIS présenté comme réel. Vérifie :
identité événement, marché, sélections, cotes bookmaker (préservées à l'identique,
aucune recomputation), horodatage, provenance ; et que l'infra de capture distingue
strictement une source LIVE d'une source SYNTHÉTIQUE.

NB Decimal : le contrat BE transporte les cotes en `float` (RawSelection.decimal_odds:
float) — choix gelé antérieur à ce chantier. La fidélité testée ici = préservation
EXACTE de la valeur source sans recomputation ; la sécurité Decimal est imposée en
aval, à la frontière Advisor (input_adapter), déjà en place.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.betting_engine.bookmakers.protocol import MarketType
from src.agents.quant.betting_engine.bookmakers.winamax.catalogue import supported_events
from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import (
    SOURCE_LIVE,
    SOURCE_SYNTHETIC,
    capture_live_state,
    load_capture,
    replay,
    save_capture,
    synthetic_capture,
)

_NOW = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
_KICKOFF_EPOCH = 1772359200          # 2026-03-01T18:00:00Z


def _fl1_state() -> dict:
    """PRELOADED_STATE synthétique fidèle à la structure Winamax (une rencontre FL1)."""
    return {
        "matches": {
            "77001": {
                "sportId": 1, "tournamentId": 4, "isOutright": False,
                "competitor1Id": 1301, "competitor1Name": "Paris Saint-Germain",
                "competitor2Id": 1302, "competitor2Name": "Olympique de Marseille",
                "matchStart": _KICKOFF_EPOCH, "status": "PREMATCH",
            },
        },
        "bets": {
            "9001": {
                "matchId": 77001, "betType": 1, "betTypeName": "Résultat",
                "template": "3way", "betTypeIsLive": False, "outcomes": [501, 502, 503],
            },
        },
        "outcomes": {
            "501": {"code": "1", "label": "Paris Saint-Germain"},
            "502": {"code": "x", "label": "Match nul"},
            "503": {"code": "2", "label": "Olympique de Marseille"},
        },
        "odds": {"501": 1.55, "502": 4.30, "503": 6.10},
        "tournaments": {"4": {"tournamentName": "Ligue 1 McDonald's®"}},
    }


def test_replay_is_faithful_to_source_payload():
    capture = synthetic_capture(_fl1_state(), "football", now=_NOW)
    events = replay(capture, now=_NOW)
    assert len(events) == 1
    ev = events[0]

    # Identité événement + provenance.
    assert ev.bookmaker == "winamax"
    assert ev.bookmaker_event_id == "77001"
    assert ev.slot_1_name == "Paris Saint-Germain" and ev.slot_2_name == "Olympique de Marseille"
    assert ev.raw_tournament_id == "4"
    assert ev.competition == "Ligue 1 McDonald's®"
    # Horodatage : epoch source -> datetime UTC fidèle.
    assert ev.start_time == datetime.fromtimestamp(_KICKOFF_EPOCH, tz=timezone.utc)
    assert ev.fetched_at == _NOW

    # Marché + sélections.
    assert len(ev.markets) == 1
    market = ev.markets[0]
    assert market.market_type is MarketType.MATCH_WINNER
    assert market.template == "3way"
    codes = {s.code: s for s in market.selections}
    assert set(codes) == {"1", "x", "2"}
    # Cotes préservées EXACTEMENT (aucune recomputation).
    assert codes["1"].decimal_odds == 1.55
    assert codes["x"].decimal_odds == 4.30
    assert codes["2"].decimal_odds == 6.10
    assert codes["x"].canonical_selection == "draw"


def test_supported_events_keeps_resolved_ligue1_match():
    capture = synthetic_capture(_fl1_state(), "football", now=_NOW)

    class _Conn:
        def scan_catalog(self, sport="football"):
            return replay(capture, now=_NOW)

    kept = supported_events(_Conn(), "football")
    assert len(kept) == 1 and kept[0].bookmaker_event_id == "77001"


def test_capture_roundtrip_preserves_payload_and_provenance(tmp_path):
    capture = synthetic_capture(_fl1_state(), "football", now=_NOW)
    path = tmp_path / "winamax_fl1.json"
    save_capture(capture, path)
    reloaded = load_capture(path)
    assert reloaded.source == SOURCE_SYNTHETIC          # jamais promu en LIVE
    assert reloaded.is_authentic is False
    assert replay(reloaded, now=_NOW)[0].bookmaker_event_id == "77001"


def test_synthetic_is_never_labeled_authentic():
    capture = synthetic_capture(_fl1_state(), "football", now=_NOW)
    assert capture.source == SOURCE_SYNTHETIC and capture.is_authentic is False


def test_capture_live_state_marks_source_live_only_when_fetched():
    """L'infra PEUT enregistrer un vrai payload : `fetch` injecté simule le réseau
    (aucun appel réel en CI). Le résultat est marqué LIVE — seule voie vers
    `is_authentic`. Une fixture synthétique ne peut jamais l'obtenir."""
    captured = capture_live_state("football", fetch=lambda sport_id: _fl1_state(), now=_NOW)
    assert captured.source == SOURCE_LIVE and captured.is_authentic is True
    assert replay(captured, now=_NOW)[0].bookmaker_event_id == "77001"
