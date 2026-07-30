"""Collecte odds_history OPÉRATIONNELLE (BE-FR-015) : scan/replay -> OddsObservation
-> store -> CLV mesurable. Hermétique. Prouve que le temps qui passe (DECISION puis
CLOSING) produit les paires dont la CLV a besoin, avec une provenance honnête et
Decimal préservé. Aucune donnée fabriquée : les cotes proviennent d'une capture,
marquée SYNTHÉTIQUE (jamais présentée comme réelle).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import synthetic_capture
from src.agents.quant.betting_engine.clv import (
    JsonlOddsHistoryStore,
    MEASURABLE,
    NOT_YET_MEASURABLE,
    ObservationPhase,
    clv_readiness,
    record_from_capture,
)
from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver

_KO_EPOCH = 1772359200          # 2026-03-01T18:00:00Z


def _resolver():
    identity = IdentityResolver([
        CanonicalEntity("team:football:fra:psg", "Paris Saint Germain",
                        ["PSG", "Paris SG", "Paris Saint-Germain"], {}),
        CanonicalEntity("team:football:fra:marseille", "Marseille",
                        ["OM", "Olympique de Marseille"], {})])
    comp = lambda tid: (("competition:football:fra:ligue1", "RESOLVED", "competition_table")
                        if tid == "4" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _fl1_state(*, home_odds):
    """PRELOADED_STATE synthétique fidèle (PSG vs OM, Ligue 1). L'instant d'observation
    des cotes est fixé au REPLAY (`now`), pas dans l'état."""
    return {
        "matches": {"77001": {
            "sportId": 1, "tournamentId": 4, "isOutright": False,
            "competitor1Id": 1301, "competitor1Name": "Paris Saint-Germain",
            "competitor2Id": 1302, "competitor2Name": "Marseille",
            "matchStart": _KO_EPOCH, "status": "PREMATCH"}},
        "bets": {"9001": {"matchId": 77001, "betType": 1, "betTypeName": "Résultat",
                          "template": "3way", "betTypeIsLive": False, "outcomes": [501, 502, 503]}},
        "outcomes": {"501": {"code": "1", "label": "PSG"},
                     "502": {"code": "x", "label": "Nul"},
                     "503": {"code": "2", "label": "OM"}},
        "odds": {"501": home_odds, "502": 4.30, "503": 6.10},
        "tournaments": {"4": {"tournamentName": "Ligue 1"}},
    }


def _capture(*, home_odds):
    return synthetic_capture(_fl1_state(home_odds=home_odds), "football")


def test_recording_a_scan_persists_canonical_observations(tmp_path):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    summary = record_from_capture(
        _capture(home_odds=2.10), event_resolver=_resolver(), store=store,
        phase=ObservationPhase.DECISION, run_id="run-decision", now=t0)
    assert summary.events_recorded == 1
    assert summary.observations_written == 3            # home/draw/away
    obs = store.all()
    assert {o.selection for o in obs} == {"home", "draw", "away"}
    home = next(o for o in obs if o.selection == "home")
    assert home.decimal_odds == Decimal("2.1") and isinstance(home.decimal_odds, Decimal)
    assert home.source == "synthetic"                   # provenance honnête, jamais "réel"
    assert home.event_id.startswith("event:")           # identité canonique


def test_decision_then_closing_makes_clv_measurable(tmp_path):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    resolver = _resolver()
    t_decision = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    t_closing = datetime(2026, 3, 1, 17, 30, tzinfo=timezone.utc)   # près du coup d'envoi

    # Avant toute collecte : CLV non mesurable.
    assert clv_readiness(store.all()).status == NOT_YET_MEASURABLE

    record_from_capture(_capture(home_odds=2.10), event_resolver=resolver,
                        store=store, phase=ObservationPhase.DECISION, now=t_decision)
    # Décision seule : toujours non mesurable (pas de clôture).
    assert clv_readiness(store.all()).status == NOT_YET_MEASURABLE

    record_from_capture(_capture(home_odds=1.90), event_resolver=resolver,
                        store=store, phase=ObservationPhase.CLOSING, now=t_closing)
    readiness = clv_readiness(store.all())
    assert readiness.status == MEASURABLE                # la paire décision/clôture existe
    assert readiness.n_complete_pairs == 3               # home/draw/away appariés
    assert readiness.mean_clv is not None                # valeur réelle, jamais None->0


def test_unresolved_events_are_skipped_never_fabricated(tmp_path):
    store = JsonlOddsHistoryStore(tmp_path / "odds.jsonl")
    t0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    # Résolveur qui ne résout AUCUNE équipe -> événement ignoré, rien fabriqué.
    empty = BookmakerEventResolver(IdentityResolver([]),
                                   competition_resolver=lambda tid: (None, "UNRESOLVED", "none"))
    summary = record_from_capture(_capture(home_odds=2.10), event_resolver=empty,
                                  store=store, phase=ObservationPhase.DECISION, now=t0)
    assert summary.observations_written == 0 and summary.events_skipped == 1
    assert store.all() == []
