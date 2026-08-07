"""Couche Winamax UNIFIÉE — une SEULE source canonique (PRELOADED_STATE connector).

Prouve : (1) l'ancien `odds_fetcher`/`odds_provider` (sportId faux tennis=2, forme 1N2
codée en dur) est SUPPRIMÉ ; (2) coverage, recommend, record-odds et winamax_odds_fetch
consomment EXACTEMENT les mêmes événements (`parse_catalog`) ; (3) régression du bug :
un marché 2-way (tennis) ne fabrique plus de `draw:None` et ne lève plus de TypeError.
Hermétique (un PRELOADED_STATE synthétique rejoué ; opt-in réseau pour le live).
"""

from __future__ import annotations

import importlib
import os

import pytest

from src.agents.quant.betting_engine.bookmakers.winamax.catalogue import all_events, multisport_events
from src.agents.quant.betting_engine.bookmakers.winamax.connector import SPORT_IDS, parse_catalog
from src.agents.quant.betting_engine.bookmakers.winamax.odds_quotes import fetch_odds_quotes
from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import replay, synthetic_capture
from src.agents.quant.betting_engine.value_engine import margin_removal

_EPOCH = 1772359200          # 2026-03-01T18:00:00Z


def _tennis_state():         # 2-way « Vainqueur » (le cas qui plantait)
    return {
        "matches": {"70001": {"sportId": 5, "tournamentId": "T1", "isOutright": False,
                              "competitor1Id": 901, "competitor1Name": "Carlos Alcaraz",
                              "competitor2Id": 902, "competitor2Name": "Jannik Sinner",
                              "matchStart": _EPOCH, "status": "PREMATCH"}},
        "bets": {"8001": {"matchId": "70001", "betType": 112, "betTypeName": "Vainqueur",
                          "template": "2way", "betTypeIsLive": False, "outcomes": [601, 602]}},
        "outcomes": {"601": {"code": "1", "label": "Alcaraz"}, "602": {"code": "2", "label": "Sinner"}},
        "odds": {"601": 1.30, "602": 3.50},
        "tournaments": {"T1": {"tournamentName": "ATP Masters"}}}


def _football_state():       # 3-way « Résultat » (draw RÉEL, pas fabriqué)
    return {
        "matches": {"77001": {"sportId": 1, "tournamentId": "4", "isOutright": False,
                              "competitor1Id": 1301, "competitor1Name": "Paris Saint-Germain",
                              "competitor2Id": 1302, "competitor2Name": "Marseille",
                              "matchStart": _EPOCH, "status": "PREMATCH"}},
        "bets": {"9001": {"matchId": "77001", "betType": 1, "betTypeName": "Résultat",
                          "template": "3way", "betTypeIsLive": False, "outcomes": [501, 502, 503]}},
        "outcomes": {"501": {"code": "1", "label": "PSG"}, "502": {"code": "x", "label": "Nul"},
                     "503": {"code": "2", "label": "OM"}},
        "odds": {"501": 1.50, "502": 4.30, "503": 6.10},
        "tournaments": {"4": {"tournamentName": "Ligue 1"}}}


class _FakeConnector:
    """Connecteur hermétique : scan_catalog délègue au MÊME `parse_catalog` canonique."""
    def __init__(self, state):
        self._state = state

    def scan_catalog(self, sport):
        return parse_catalog(self._state, sport, SPORT_IDS[sport])


# ── (1) Plus de second chemin : legacy supprimé ──────────────────────────────────
@pytest.mark.parametrize("mod", ["src.agents.quant.odds_fetcher",
                                 "src.agents.quant.gateway.providers.odds_provider"])
def test_legacy_winamax_paths_are_removed(mod):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(mod)


# ── (2) Source unique : les 4 consommateurs voient les MÊMES événements ───────────
def test_all_consumers_share_parse_catalog():
    state = _football_state()
    ref = parse_catalog(state, "football", SPORT_IDS["football"])
    ref_ids = {e.bookmaker_event_id for e in ref}
    conn = _FakeConnector(state)
    # record-odds (replay) — même parse_catalog
    assert {e.bookmaker_event_id for e in replay(synthetic_capture(state, "football"))} == ref_ids
    # coverage / recommend (catalogue) — même connecteur
    assert {e.bookmaker_event_id for e in all_events(conn, "football")} == ref_ids
    assert {e.bookmaker_event_id for e in multisport_events(conn, ["football"])} == ref_ids
    # winamax_odds_fetch (odds_quotes) — même connecteur
    assert {q.match_id for q in fetch_odds_quotes("football", connector=conn)} == ref_ids


# ── (3) Régression : 2-way -> {slot_1, slot_2}, jamais draw:None, jamais TypeError ─
def test_two_way_market_has_no_fabricated_draw_and_no_typeerror():
    quotes = fetch_odds_quotes("tennis", connector=_FakeConnector(_tennis_state()))
    assert len(quotes) == 1
    q = quotes[0]
    assert set(q.odds) == {"slot_1", "slot_2"}               # aucune sélection « draw » fabriquée
    assert None not in q.odds.values()
    # le calcul qui plantait (implied_raw sur chaque sélection présente) ne lève plus
    implied = {k: round(margin_removal.implied_raw(v), 4) for k, v in q.odds.items()}
    assert set(implied) == {"slot_1", "slot_2"} and all(0 < p < 1 for p in implied.values())


def test_three_way_market_keeps_real_draw():
    q = fetch_odds_quotes("football", connector=_FakeConnector(_football_state()))[0]
    assert set(q.odds) == {"slot_1", "draw", "slot_2"}       # draw RÉEL (3-way), présent


def test_odds_quotes_route_through_connector_scan_catalog():
    calls = []

    class _Spy(_FakeConnector):
        def scan_catalog(self, sport):
            calls.append(sport)
            return super().scan_catalog(sport)

    fetch_odds_quotes("tennis", connector=_Spy(_tennis_state()))
    assert calls == ["tennis"]                               # une seule source, appelée une fois


# ── (5) LIVE opt-in : vrai fetch, aucun fallback/fixture ─────────────────────────
@pytest.mark.skipif(os.environ.get("AXON_LIVE") != "1",
                    reason="live opt-in : définir AXON_LIVE=1 (jamais en CI)")
def test_live_multisport_odds_fetch_no_fallback():   # pragma: no cover (réseau réel)
    for sport in ("football", "basketball", "hockey", "tennis"):
        quotes = fetch_odds_quotes(sport)            # vrai réseau via WinamaxConnector
        for q in quotes:
            assert None not in q.odds.values() and len(q.odds) >= 2
            {k: margin_removal.implied_raw(v) for k, v in q.odds.items()}   # ne lève jamais
        print(f"{sport}: {len(quotes)} quotes (source unique PRELOADED_STATE)")


# ══ Scan multisport : de front, mais déterministe ══════════════════════════
def test_le_scan_multisport_conserve_l_ordre_des_sports_demandes():
    """Les scans partent ensemble — sept appels réseau enchaînés coûtaient leur
    somme (0,98 s mesurée) alors qu'ils ne dépendent pas les uns des autres.

    L'ordre de sortie doit rester celui des sports DEMANDÉS, jamais celui des
    réponses : deux runs identiques doivent produire le même catalogue, dans le
    même ordre, sinon un classement aval hériterait d'un aléa réseau.
    """
    import time

    from src.agents.quant.betting_engine.bookmakers.winamax.catalogue import multisport_events

    class _Lent:
        """Le premier sport répond en dernier — cas qui révèle un tri par arrivée."""
        def scan_catalog(self, sport):
            if sport == "a":
                time.sleep(0.05)
            return [f"{sport}-1", f"{sport}-2"]

    assert list(multisport_events(_Lent(), ["a", "b", "c"])) == [
        "a-1", "a-2", "b-1", "b-2", "c-1", "c-2"]


def test_le_scan_multisport_mene_les_sports_de_front():
    import threading
    import time

    from src.agents.quant.betting_engine.bookmakers.winamax.catalogue import multisport_events

    simultanes, maximum, verrou = 0, 0, threading.Lock()

    class _Compteur:
        def scan_catalog(self, sport):
            nonlocal simultanes, maximum
            with verrou:
                simultanes += 1
                maximum = max(maximum, simultanes)
            time.sleep(0.05)
            with verrou:
                simultanes -= 1
            return []

    multisport_events(_Compteur(), ["a", "b", "c", "d"])

    assert maximum >= 2, "les scans sont restés séquentiels"


def test_un_scan_qui_echoue_reste_une_panne_pas_un_sport_vide():
    """Confondre les deux ferait répondre « rien aujourd'hui » à une coupure."""
    import pytest

    from src.agents.quant.betting_engine.bookmakers.winamax.catalogue import multisport_events

    class _Casse:
        def scan_catalog(self, sport):
            if sport == "b":
                raise ConnectionError("winamax injoignable")
            return [f"{sport}-1"]

    with pytest.raises(ConnectionError):
        multisport_events(_Casse(), ["a", "b", "c"])
