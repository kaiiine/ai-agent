"""Tennis LIVE câblé (Phase 5) — le VRAI modèle Elo traverse le chemin live GÉNÉRIQUE.

Hermétique (dataset embarqué + alias réels, zéro réseau). Prouve : identité JOUEUR
(pont Winamax « Novak Djokovic » <-> dataset « Djokovic N. », clé exacte jamais fuzzy),
marché 2-way `player_a/player_b` (aucun home/away ni draw fabriqué), Elo point-in-time,
freshness Gateway->BE mesurée, EXPERIMENTAL -> ABSTAIN, joueur inconnu isolé,
circuits ATP/WTA jamais croisés.
"""

from __future__ import annotations

import functools
import os
from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
    evaluate_live_event,
)
from src.agents.quant.betting_engine.sports.tennis.identity import (
    dataset_key, tennis_players, winamax_key,
)
from src.agents.quant.betting_engine.sports.tennis.live_model import TENNIS_MODULE, all_tennis_players

_DECISION = datetime(2024, 6, 1, 12, tzinfo=timezone.utc)     # historique 2015-2024 suffisant
_START = _DECISION + timedelta(hours=6)


class _Fresh:
    effective_time, freshness_score, degraded = _DECISION - timedelta(hours=2), 0.9, False


class _Gateway:
    def data_freshness(self, competition_id, season):
        return _Fresh()


@functools.lru_cache(maxsize=2)
def _alias_pair(tour: str) -> tuple[str, str]:
    """Deux joueurs RÉELS du circuit ayant un alias Winamax vérifié ET assez d'historique
    (les plus expérimentés) — sinon le cold-start légitime bloque avant la prédiction."""
    from collections import Counter
    from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import load_tennis_data
    counts: Counter = Counter()
    for m in load_tennis_data(tour).matches:
        counts[m.p1_name] += 1
        counts[m.p2_name] += 1
    ents, _ = tennis_players(tour)
    named = sorted((e for e in ents if e.aliases), key=lambda e: -counts[e.canonical_name])
    assert len(named) >= 2 and counts[named[1].canonical_name] >= 20, f"pas assez d'alias {tour}"
    return named[0].aliases[0], named[1].aliases[0]


def _resolver():
    comp = lambda tid: (("competition:tennis:atp:tour", "RESOLVED", "competition_table")
                        if tid == "ATP" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(IdentityResolver(list(all_tennis_players())),
                                  competition_resolver=comp)


def _event(p1: str, p2: str):
    market = RawMarket(MarketType.MATCH_WINNER, 112, "Vainqueur", "2way", False, None,
                       [RawSelection("1", p1, 1.55, "slot_1"), RawSelection("2", p2, 2.45, "slot_2")])
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="ATP_1", sport="tennis", competition="ATP",
        slot_1_name=p1, slot_2_name=p2, slot_1_id=None, slot_2_id=None,
        start_time=_START, status="PREMATCH", is_outright=False,
        markets=[market], fetched_at=_DECISION, raw_tournament_id="ATP")


def _run(event):
    return evaluate_live_event(
        event, decision_time=_DECISION, event_resolver=_resolver(), sports_gateway=_Gateway(),
        sport_modules={"tennis": TENNIS_MODULE}, coverage_check=lambda *a: ["embedded_dataset"])


# ── Pont d'identité : normalisation EXACTE, jamais approximative ─────────────────
def test_identity_bridge_keys_match_exactly():
    assert winamax_key("Novak Djokovic") == ("djokovic", "n") == dataset_key("Djokovic N.")
    assert winamax_key("Felix Auger-Aliassime") == dataset_key("Auger-Aliassime F.")
    assert winamax_key("A.Klepac / M.Ninomiya") is None       # double = paire, jamais un joueur
    assert winamax_key("Djokovic") is None                    # nom seul : non décidable


def test_ambiguous_key_gets_no_alias_never_misresolved():
    # Deux joueurs partageant (nom, initiale) ne reçoivent AUCUN alias Winamax.
    ents, _ = tennis_players("atp")
    by_key: dict = {}
    for e in ents:
        k = dataset_key(e.canonical_name)
        if k:
            by_key.setdefault(k, []).append(e)
    ambiguous = [v for v in by_key.values() if len(v) > 1]
    assert ambiguous, "le dataset doit contenir des clés homonymes (sinon test vide)"
    for group in ambiguous:
        assert all(not e.aliases for e in group)              # jamais rattaché au hasard


# ── Chemin live générique ────────────────────────────────────────────────────────
def test_real_elo_model_evaluates_two_way_with_measured_freshness():
    p1, p2 = _alias_pair("atp")
    res = _run(_event(p1, p2))
    assert res.status is S.EVALUATED
    assert set(res.predictions) == {"player_a", "player_b"}   # 2-way neutre, ni home/away ni draw
    pa = res.predictions["player_a"].fair_probability
    assert 0.0 < pa < 1.0
    assert abs(pa + res.predictions["player_b"].fair_probability - 1.0) < 1e-9
    assert res.predictions["player_a"].calibration_status.value == "EXPERIMENTAL"
    assert all(d.decision == "ABSTAIN" for d in res.decisions)   # cap BE-FR-011
    assert res.freshness_score == 0.9                            # Gateway -> BE mesurée


def test_point_in_time_features_only_prior_matches():
    p1, p2 = _alias_pair("atp")
    fs = _run(_event(p1, p2)).feature_set
    assert fs.as_of == _DECISION and fs.sport == "tennis"
    assert fs.event_features["tour"] == "atp"
    assert all(pf["prior_matches"] >= 20 for pf in fs.participant_features.values())


def test_unknown_player_is_isolated():
    p1, _ = _alias_pair("atp")
    assert _run(_event(p1, "Joueur Inexistant")).status is S.EVENT_NOT_RESOLVED


def test_cross_tour_event_never_evaluated():
    # Un ATP contre une WTA : circuits distincts -> aucune probabilité fabriquée.
    atp1, _ = _alias_pair("atp")
    wta1, _ = _alias_pair("wta")
    res = _run(_event(atp1, wta1))
    assert res.status in (S.INSUFFICIENT_FEATURES, S.EVENT_NOT_RESOLVED)


# ── Live opt-in : vrai scan Winamax, aucun fallback ──────────────────────────────
@pytest.mark.skipif(os.environ.get("AXON_LIVE") != "1",
                    reason="live opt-in : définir AXON_LIVE=1 (jamais en CI)")
def test_live_tennis_scan_reaches_model_or_typed_rejection():   # pragma: no cover (réseau réel)
    from collections import Counter
    from src.agents.quant.betting_engine.bookmakers.winamax.connector import WinamaxConnector
    events = WinamaxConnector().scan_catalog("tennis")
    now = datetime.now(timezone.utc)
    statuses = Counter()
    for e in events:
        r = evaluate_live_event(
            e, decision_time=now, event_resolver=_resolver(), sports_gateway=_Gateway(),
            sport_modules={"tennis": TENNIS_MODULE}, coverage_check=lambda *a: ["embedded_dataset"])
        statuses[r.status.value] += 1
    print(f"tennis live: {len(events)} events -> {dict(statuses)}")
    assert sum(statuses.values()) == len(events)          # chaque événement a un statut TYPÉ
