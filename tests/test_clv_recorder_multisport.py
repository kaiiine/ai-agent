"""record-odds RÉELLEMENT multisport pour les 6 (§15/§25) — hermétique.

Prouve que la collecte odds_history fonctionne pour les 3 sports fraîchement câblés
(baseball, NFL, volley) via l'identité AGRÉGÉE (`all_sport_teams`) et le schéma dérivé
du registre de modèles (2-way) : DECISION puis CLOSING -> paire CLV mesurable, comme le
football (3-way) et le basket (2-way) déjà couverts par test_clv_recorder. Aucune cote
fabriquée : les cotes viennent d'une capture marquée SYNTHÉTIQUE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import synthetic_capture
from src.agents.quant.betting_engine.clv import (
    MEASURABLE, JsonlOddsHistoryStore, ObservationPhase, clv_readiness, record_from_capture,
)
from src.agents.quant.betting_engine.sports.identity_aggregate import all_sport_teams

_KO = 1772359200          # 2026-03-01T18:00:00Z

# (sport canonique, sportId Winamax, tournamentId, canonical competition, home, away)
CASES = {
    "baseball": (3, 4101, "competition:baseball:usa:mlb", "Boston Red Sox", "Minnesota Twins"),
    "american_football": (16, 4102, "competition:american_football:usa:nfl",
                          "Las Vegas Raiders", "Cincinnati Bengals"),
    "volleyball": (23, 4103, "competition:volleyball:ita:serie_a1", "Vero Volley W", "Bergamo W"),
}


def _resolver(tournament_id, canonical):
    comp = lambda tid: ((canonical, "RESOLVED", "competition_table")
                        if str(tid) == str(tournament_id) else (None, "UNRESOLVED", "none"))
    # Résolveur MULTISPORT partagé (identité agrégée des 6 sports).
    return BookmakerEventResolver(IdentityResolver(list(all_sport_teams())), competition_resolver=comp)


def _capture(sport, sport_id, tournament_id, home, away, home_odds):
    state = {
        "matches": {"90001": {
            "sportId": sport_id, "tournamentId": tournament_id, "isOutright": False,
            "competitor1Id": 3001, "competitor1Name": home,
            "competitor2Id": 3002, "competitor2Name": away,
            "matchStart": _KO, "status": "PREMATCH"}},
        "bets": {"9003": {"matchId": 90001, "betType": 1, "betTypeName": "Vainqueur",
                          "template": "2way", "betTypeIsLive": False, "outcomes": [701, 702]}},
        "outcomes": {"701": {"code": "1", "label": home}, "702": {"code": "2", "label": away}},
        "odds": {"701": home_odds, "702": 2.10},
        "tournaments": {str(tournament_id): {"tournamentName": str(tournament_id)}}}
    return synthetic_capture(state, sport)


@pytest.mark.parametrize("sport", list(CASES))
def test_record_odds_collects_clv_for_each_live_wired_sport(sport, tmp_path):
    sport_id, tid, canonical, home, away = CASES[sport]
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    t0 = datetime(2026, 3, 1, 10, tzinfo=timezone.utc)
    resolver = _resolver(tid, canonical)

    dec = record_from_capture(_capture(sport, sport_id, tid, home, away, 1.80),
                              event_resolver=resolver, store=store,
                              phase=ObservationPhase.DECISION, now=t0)
    assert dec.events_recorded == 1 and dec.observations_written == 2   # home/away (2-way, aucun nul)
    assert {o.selection for o in store.all()} == {"home", "away"}

    record_from_capture(_capture(sport, sport_id, tid, home, away, 1.60),
                        event_resolver=resolver, store=store,
                        phase=ObservationPhase.CLOSING, now=t0 + timedelta(hours=6))
    r = clv_readiness(store.all())
    assert r.status == MEASURABLE and r.n_complete_pairs == 2 and r.n_events == 1
