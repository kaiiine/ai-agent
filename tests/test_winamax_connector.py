"""Parsing du catalogue Winamax -> RawBookmakerEvent (connector.parse_catalog).

Hermétique : `PRELOADED_STATE` synthétique bâti sur des lignes réelles de la
cartographie (Copenhague-Lyngby 1X2, Bondar-Korpatsch 2-way, un outright F1 à
exclure, un match baseball pour tester le filtre sport). Aucun réseau.
"""

from __future__ import annotations

import pytest

from src.agents.quant.betting_engine.bookmakers.protocol import MarketType
from src.agents.quant.betting_engine.bookmakers.winamax import connector


def _state() -> dict:
    return {
        "matches": {
            # Football — Superliga (tournoi 12), 1X2 (carto §7/§9).
            "71924938": {
                "sportId": 1, "competitor1Id": 1284, "competitor1Name": "Copenhague",
                "competitor2Id": 1756, "competitor2Name": "Lyngby",
                "matchStart": 1785074400, "status": "PREMATCH", "isOutright": False,
                "mainBetId": 656873474, "tournamentId": 12,
                "srTournamentId": "sr:tournament:39",
            },
            # Tennis — WTA Hambourg (tournoi 179018), 2-way.
            "72829952": {
                "sportId": 5, "competitor1Id": 150574, "competitor1Name": "Anna Bondar",
                "competitor2Id": 69988, "competitor2Name": "Tamara Korpatsch",
                "matchStart": 1785067200, "status": "PREMATCH", "isOutright": False,
                "mainBetId": 668910944, "tournamentId": 179018,
                "srTournamentId": "sr:tournament:34272",
            },
            # Outright F1 (pas de deux compétiteurs) -> doit être exclu.
            "1000128218": {
                "sportId": 40, "competitor1Name": None, "competitor2Name": None,
                "matchStart": 1785070800, "status": "PREMATCH", "isOutright": True,
                "tournamentId": 900005133,
            },
            # Baseball -> filtré quand on scanne le football.
            "63299181": {
                "sportId": 3, "competitor1Id": 3652, "competitor1Name": "Baltimore Orioles",
                "competitor2Id": 3656, "competitor2Name": "Atlanta Braves",
                "matchStart": 1785020700, "status": "PREMATCH", "isOutright": False,
                "mainBetId": 668415249, "tournamentId": 25,
            },
        },
        "bets": {
            "656873474": {
                "matchId": 71924938, "betType": 3178, "betTypeName": "Résultat",
                "template": "3way", "betTypeIsLive": False,
                "specialBetValue": "type=prematch",
                "outcomes": [2044624131, 2044624132, 2044624133],
            },
            "668910944": {
                "matchId": 72829952, "betType": 3624, "betTypeName": "Vainqueur",
                "template": "2way", "betTypeIsLive": False,
                "specialBetValue": "type=prematch",
                "outcomes": [2080536986, 2080536987],
            },
            "668415249": {
                "matchId": 63299181, "betType": 3294, "betTypeName": "Vainqueur",
                "template": "2way", "betTypeIsLive": False, "specialBetValue": None,
                "outcomes": [2079064406, 2079064407],
            },
        },
        "outcomes": {
            "2044624131": {"code": "1", "label": "Copenhague"},
            "2044624132": {"code": "x", "label": "Match nul"},
            "2044624133": {"code": "2", "label": "Lyngby"},
            "2080536986": {"code": "1", "label": "Anna Bondar"},
            "2080536987": {"code": "2", "label": "Tamara Korpatsch"},
            "2079064406": {"code": "1", "label": "Baltimore Orioles"},
            "2079064407": {"code": "2", "label": "Atlanta Braves"},
        },
        "odds": {
            "2044624131": 1.33, "2044624132": 4.6, "2044624133": 5.3,
            "2080536986": 1.5, "2080536987": 2.5,
            "2079064406": 1.8, "2079064407": 2.0,
        },
        "tournaments": {
            "12": {"tournamentName": "Superliga"},
            "179018": {"tournamentName": "Hamburg"},
            "25": {"tournamentName": "MLB"},
        },
    }


def test_football_event_parsed_in_slots_no_home_away():
    events = connector.parse_catalog(_state(), "football", 1)
    assert len(events) == 1
    ev = events[0]
    assert ev.bookmaker == "winamax"
    assert ev.bookmaker_event_id == "71924938"
    assert ev.competition == "Superliga"
    # slots bruts, ordre préservé, AUCUN champ home/away sur l'objet d'acquisition
    assert (ev.slot_1_name, ev.slot_2_name) == ("Copenhague", "Lyngby")
    assert not hasattr(ev, "home")
    assert ev.status == "PREMATCH"
    assert ev.sr_tournament_id == "sr:tournament:39"


def test_football_market_and_selections_mapped():
    ev = connector.parse_catalog(_state(), "football", 1)[0]
    assert len(ev.markets) == 1
    market = ev.markets[0]
    assert market.market_type == MarketType.MATCH_WINNER
    assert market.template == "3way"
    assert market.raw_bet_type == 3178
    # 1 / x / 2 -> slot_1 / draw / slot_2, avec les cotes réelles
    by_canon = {s.canonical_selection: s for s in market.selections}
    assert by_canon["slot_1"].decimal_odds == 1.33
    assert by_canon["draw"].label == "Match nul"
    assert by_canon["slot_2"].decimal_odds == 5.3


def test_offer_fields_default_to_non_boosted():
    # Périmètre pré-match non boosté : les champs d'offre restent par défaut,
    # max_payout notamment jamais peuplé (aucune extraction).
    ev = connector.parse_catalog(_state(), "football", 1)[0]
    sel = ev.markets[0].selections[0]
    assert sel.is_boosted is False
    assert sel.boost_reference_odds is None
    assert sel.max_stake is None
    assert sel.max_payout is None


def test_sport_filter_excludes_other_sports_and_outrights():
    football = connector.parse_catalog(_state(), "football", 1)
    tennis = connector.parse_catalog(_state(), "tennis", 5)
    assert [e.bookmaker_event_id for e in football] == ["71924938"]
    assert [e.bookmaker_event_id for e in tennis] == ["72829952"]
    # l'outright F1 (sportId 40) n'apparaît dans aucun scan
    assert all(not e.is_outright for e in football + tennis)


def test_tennis_two_way_has_no_draw_selection():
    ev = connector.parse_catalog(_state(), "tennis", 5)[0]
    codes = {s.canonical_selection for s in ev.markets[0].selections}
    assert codes == {"slot_1", "slot_2"}
    assert "draw" not in codes


def test_start_time_is_timezone_aware_utc():
    ev = connector.parse_catalog(_state(), "football", 1)[0]
    assert ev.start_time is not None
    assert ev.start_time.tzinfo is not None
