"""CLI adaptateur live — hermétique, scan fake (zéro réseau).

Vérifie : filtrage catalogue, rendu DIFFÉRENCIÉ (probas seulement si vraie
prédiction), les 3 codes de sortie, poursuite du run malgré un échec individuel.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.gateway.core.errors import NoDataAvailableError
from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.bookmakers.winamax.catalogue import supported_events
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as St, evaluate_live_event,
)
from src.agents.quant.betting_engine import cli

_PSG = "team:football:fra:psg"
_OM = "team:football:fra:marseille"
_KO = datetime(2025, 10, 5, 17, tzinfo=timezone.utc)
_DEC = datetime(2025, 10, 4, 12, tzinfo=timezone.utc)
_DATES = ["2025-09-28", "2025-09-21", "2025-09-14", "2025-08-31", "2025-08-24"]


def _form(pairs):
    return [{"is_home": h, "goals_home": gh, "goals_away": ga, "opponent_id": f"o{i}",
             "date": _DATES[i], "league_id": "L", "season": "2025"}
            for i, (h, gh, ga) in enumerate(pairs)]


class _FakeGateway:
    def __init__(self, forms, standings):
        self._forms, self._standings = forms, standings

    def recent_form(self, cid, last, season):
        if cid not in self._forms:
            raise NoDataAvailableError(cid)
        return self._forms[cid][:last]

    def standings_strength(self, comp, season):
        return dict(self._standings)


class _FakeConnector:
    def __init__(self, events, raise_exc=None):
        self._events, self._raise = events, raise_exc

    def scan_catalog(self, sport="football"):
        if self._raise:
            raise self._raise
        return list(self._events)


def _resolver():
    identity = IdentityResolver([
        CanonicalEntity(_PSG, "Paris Saint Germain", ["PSG", "Paris SG", "Paris Saint-Germain"], {}),
        CanonicalEntity(_OM, "Marseille", ["OM"], {}),
    ])
    comp = lambda tid: (("competition:football:fra:ligue1", "RESOLVED", "competition_table")
                        if tid == "4" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _event(bem_id="E1", tid="4", slot_1="Paris Saint-Germain", markets=None):
    market = RawMarket(MarketType.MATCH_WINNER, 3178, "Résultat", "3way", False, "type=prematch",
                       [RawSelection("1", "PSG", 1.75, "slot_1"),
                        RawSelection("x", "Nul", 3.4, "draw"),
                        RawSelection("2", "OM", 4.20, "slot_2")])
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id=bem_id, sport="football", competition="Ligue 1",
        slot_1_name=slot_1, slot_2_name="Marseille", slot_1_id="1", slot_2_id="2",
        start_time=_KO, status="PREMATCH", is_outright=False,
        markets=[market] if markets is None else markets, fetched_at=_DEC, raw_tournament_id=tid)


_COVERED = lambda comp, season, dt: ["football_data_org"]
_GW = lambda: _FakeGateway({_PSG: _form([(True, 2, 0), (False, 3, 1), (True, 3, 0), (False, 2, 1), (True, 4, 1)]),
                            _OM: _form([(True, 0, 2), (False, 0, 3), (True, 1, 2), (False, 0, 2), (True, 1, 1)])},
                           {_PSG: 1.3, _OM: 0.7})


def _evaluate_covered(event, **kw):
    return evaluate_live_event(event, coverage_check=_COVERED, **kw)


def _evaluated():
    return evaluate_live_event(_event(), decision_time=_DEC, event_resolver=_resolver(),
                               sports_gateway=_GW(), coverage_check=_COVERED)


def _refusal():
    return evaluate_live_event(_event(slot_1="Copenhague"), decision_time=_DEC,
                               event_resolver=_resolver(), sports_gateway=_GW(), coverage_check=_COVERED)


# ── Catalogue : filtrage FL1/PL (hors CLI) ────────────────────────────────────
def test_supported_events_filters_by_competition():
    conn = _FakeConnector([_event("A", tid="4"), _event("B", tid="999"), _event("C", tid="1")])
    # tid 4 = FL1 (resolver de test), 999 inconnu ; le vrai resolve_competition connaît 1=PL, 4=FL1.
    kept = {e.bookmaker_event_id for e in supported_events(conn)}
    assert "A" in kept and "C" in kept          # FL1 + PL
    assert "B" not in kept                       # tournoi inconnu écarté


# ── Rendu DIFFÉRENCIÉ (le point important) ────────────────────────────────────
def test_render_evaluated_shows_probabilities():
    res = _evaluated()
    assert res.status is St.EVALUATED
    lines = cli.render_human(_event(), res)
    assert "%" in lines[1] and "Probabilities: unavailable" not in lines[1]
    assert "MODEL_NOT_SUPPORTED" in lines[0] and "ABSTAIN" in lines[0]


def test_render_refusal_shows_unavailable_never_fake_probability():
    res = _refusal()
    assert res.status is St.EVENT_NOT_RESOLVED
    lines = cli.render_human(_event(slot_1="Copenhague"), res)
    assert "Probabilities: unavailable" in lines[1]
    assert "%" not in lines[1]                    # aucune fausse probabilité
    assert "EVENT_NOT_RESOLVED" in lines[0]


def test_json_probabilities_present_only_when_evaluated():
    ev_rec = cli.build_json_record(_event(), _evaluated())
    assert ev_rec["probabilities"] is not None and set(ev_rec["probabilities"]) == {"home", "draw", "away"}
    assert ev_rec["decision"] == "ABSTAIN"
    ref_rec = cli.build_json_record(_event(slot_1="Copenhague"), _refusal())
    assert ref_rec["probabilities"] is None       # jamais de fausse valeur
    assert ref_rec["decision"] is None


# ── Les 3 codes de sortie + définition « exploitable » ────────────────────────
def test_exit_code_zero_when_evaluated_even_if_abstain():
    # 10 événements EVALUATED (ABSTAIN/MODEL_NOT_SUPPORTED) -> exit 0.
    results = [(_event(), _evaluated()) for _ in range(10)]
    assert all(r.status is St.EVALUATED and r.decisions[0].decision == "ABSTAIN" for _, r in results)
    assert cli.exit_code_for(results) == 0


def test_exit_code_two_when_no_actionable_result():
    # 10 refus AVANT prédiction -> exit 2.
    results = [(_event(slot_1="Copenhague"), _refusal()) for _ in range(10)]
    assert cli.exit_code_for(results) == 2


def test_main_returns_one_on_total_scan_failure():
    conn = _FakeConnector([], raise_exc=RuntimeError("PRELOADED_STATE introuvable"))
    code = cli.main([], connector=conn, sports_gateway=_GW(), event_resolver=_resolver())
    assert code == 1


def test_main_exit_zero_end_to_end():
    conn = _FakeConnector([_event()])
    # coverage injecté via un evaluate enveloppé (usable_providers DB non requise en test)
    run = cli.run_live(conn, sports_gateway=_GW(), event_resolver=_resolver(),
                       evaluate=_evaluate_covered, now_fn=lambda: _DEC)
    assert cli.exit_code_for(run.results) == 0
    assert run.results[0][1].status is St.EVALUATED


# ── decision_time capturé une fois, après le scan ─────────────────────────────
def test_decision_time_captured_once_and_passed_to_every_event():
    captured = []

    def spy_evaluate(event, *, decision_time, **kw):
        captured.append(decision_time)
        return _evaluate_covered(event, decision_time=decision_time, **kw)

    conn = _FakeConnector([_event("A"), _event("B")])
    run = cli.run_live(conn, sports_gateway=_GW(), event_resolver=_resolver(),
                       evaluate=spy_evaluate, now_fn=lambda: _DEC)
    assert run.decision_time == _DEC
    assert captured == [_DEC, _DEC]               # un seul instant, jamais divergent


# ── Un échec individuel n'arrête pas le run ───────────────────────────────────
def test_individual_event_failure_does_not_stop_the_run():
    def flaky_evaluate(event, **kw):
        if event.bookmaker_event_id == "BAD":
            raise ValueError("boom interne")
        return _evaluate_covered(event, **kw)

    conn = _FakeConnector([_event("BAD"), _event("OK")])
    run = cli.run_live(conn, sports_gateway=_GW(), event_resolver=_resolver(),
                       evaluate=flaky_evaluate, now_fn=lambda: _DEC)
    assert len(run.results) == 2                   # le run continue
    by_id = {e.bookmaker_event_id: r for e, r in run.results}
    assert by_id["BAD"].status is St.GATEWAY_UNAVAILABLE
    assert by_id["BAD"].error_context["type"] == "ValueError"
    assert by_id["OK"].status is St.EVALUATED


def test_has_actionable_evaluation_property():
    assert _evaluated().has_actionable_evaluation is True
    assert _refusal().has_actionable_evaluation is False
