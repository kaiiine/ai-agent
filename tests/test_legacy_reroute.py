"""Reroute legacy -> structuré (ADR D = REROUTE_VERS_STRUCTURE). Prouve qu'il n'existe
plus de seconde pile de décision betting : les tools conversationnels délèguent au
Betting Engine et propagent l'ABSTAIN structuré. Hermétique (stubs, zéro réseau).

Invariants testés :
- aucun import de moteur legacy dans tools.py (garde statique anti-réintroduction) ;
- marché hors modèle -> MARKET_UNAVAILABLE (jamais une proba d'un moteur parallèle) ;
- ABSTAIN structuré -> ABSTAIN outil (jamais « cette cote basse est value ») ;
- combiné refusé tant que toutes les jambes ne sont pas un BET structuré ;
- source unique : la décision de l'outil == la BettingDecision structurée.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone

import src.agents.quant.tools as tools_mod
from src.agents.quant import structured_decision as sd
from src.agents.quant.betting_engine.live_evaluation import LiveEvaluationStatus

_T = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


# ── Stubs (aucun réseau) ──────────────────────────────────────────────────────
class _Dec:
    """Stand-in de BettingDecision (attributs lus par le pont)."""
    def __init__(self, selection, decision, reasons=()):
        self.selection, self.decision, self.reasons = selection, decision, list(reasons)
        self.bookmaker_odds, self.model_probability = 2.0, 0.5
        self.probability_interval, self.expected_value = (0.45, 0.55), 0.0
        self.worst_case_ev, self.no_vig_probability, self.edge = -0.1, 0.5, 0.0


class _Res:
    def __init__(self, status, reason="ok", decisions=()):
        self.status, self.reason, self.decisions = status, reason, tuple(decisions)


class _Ev:
    def __init__(self, s1, s2, comp="Ligue 1"):
        self.slot_1_name, self.slot_2_name = s1, s2
        self.competition, self.bookmaker = comp, "winamax"


def _search(mapping):
    return lambda name: ({"canonical_id": mapping[name]} if name in mapping else None)


def _cat(events):
    return lambda connector, sport="football": events


def _deps(events, evaluate, mapping):
    return dict(connector=object(), catalogue=_cat(events), event_resolver=object(),
                sports_gateway=object(), team_search=_search(mapping), evaluate=evaluate,
                decision_time=_T)


# ── Garde statique : aucune réintroduction de math betting parallèle ──────────
def test_tools_import_no_legacy_engine():
    src_text = inspect.getsource(tools_mod)
    for banned in ("quant.dixon_coles", "quant.ev_engine", "quant.probability_engine",
                   "no_vig_probabilities", "analyze_bet", "analyze_parlay"):
        assert banned not in src_text, f"réintroduction interdite : {banned}"


# ── Pont : marché hors modèle structuré ──────────────────────────────────────
def test_market_without_model_is_unavailable():
    # over/under n'a AUCUN modèle structuré -> refus, jamais un moteur legacy.
    match, sel = sd.decide_single("PSG", "Lyon", "over_2_5")
    assert match.status == sd.MARKET_UNAVAILABLE and sel is None


# ── Pont : identité non résolue -> pas de modèle ─────────────────────────────
def test_identity_unresolved_blocks_model():
    md = sd.decide_match("PSG", "Inconnu", **_deps([], lambda *a, **k: None, {"PSG": "team:psg"}))
    assert md.status == sd.IDENTITY_UNRESOLVED and not md.evaluated


# ── Pont : événement introuvable dans le catalogue ───────────────────────────
def test_event_not_found_when_no_catalogue_match():
    md = sd.decide_match("PSG", "Lyon",
                         **_deps([_Ev("PSG", "Marseille")], lambda *a, **k: None,
                                 {"PSG": "team:psg", "Lyon": "team:lyon", "Marseille": "team:om"}))
    assert md.status == sd.EVENT_NOT_FOUND


# ── Pont : modèle indisponible (structuré non EVALUATED) -> aucun fallback ────
def test_model_unavailable_maps_from_live_status():
    ev = _Ev("PSG", "Lyon")
    evaluate = lambda raw, **k: _Res(LiveEvaluationStatus.COMPETITION_NOT_COVERED, "pas de provider")
    md = sd.decide_match("PSG", "Lyon",
                         **_deps([ev], evaluate, {"PSG": "team:psg", "Lyon": "team:lyon"}))
    assert md.status == sd.MODEL_UNAVAILABLE and not md.evaluated


# ── Pont : ABSTAIN structuré traverse ────────────────────────────────────────
def test_structured_abstain_propagates():
    ev = _Ev("PSG", "Lyon")
    decisions = [_Dec("home", "ABSTAIN", ["MODEL_NOT_SUPPORTED"]),
                 _Dec("draw", "ABSTAIN", ["MODEL_NOT_SUPPORTED"]),
                 _Dec("away", "ABSTAIN", ["MODEL_NOT_SUPPORTED"])]
    evaluate = lambda raw, **k: _Res(LiveEvaluationStatus.EVALUATED, "ok", decisions)
    match, sel = sd.decide_single("PSG", "Lyon", "home",
                                  **_deps([ev], evaluate, {"PSG": "team:psg", "Lyon": "team:lyon"}))
    assert match.evaluated and sel.decision == "ABSTAIN"
    assert "MODEL_NOT_SUPPORTED" in sel.reasons


# ── Tool ev_analyze : ABSTAIN structuré -> ABSTAIN outil, jamais « value » ────
def test_ev_tool_renders_structured_abstain(monkeypatch):
    md = sd.MatchDecision(sd.EVALUATED, "ok", "PSG", "Lyon", competition="Ligue 1", bookmaker="winamax",
                          selections={"home": sd.SelectionDecision(
                              "home", "ABSTAIN", 1.48, 0.60, (0.55, 0.65), 0.02, -0.05, 0.60, 0.0,
                              ("MODEL_NOT_SUPPORTED",))})
    monkeypatch.setattr(tools_mod, "decide_single",
                        lambda h, a, m, **k: (md, md.selections["home"]))
    out = json.loads(tools_mod.ev_analyze.invoke(
        {"home_team": "PSG", "away_team": "Lyon", "market": "home", "odds": 1.48}))
    assert out["decision"] == "ABSTAIN"            # jamais BET quand le structuré ABSTAIN
    assert out["fair_probability"] == 0.60         # nombre tracé jusqu'au modèle structuré
    assert "ne pas recommander" in out["message"].lower()   # refus honnête propagé
    # `expected_value`/`worst_case_ev` sont des métriques d'audit structurées, jamais
    # présentées comme une « value » sûre : la décision reste ABSTAIN.


def test_ev_tool_market_unavailable_is_abstain(monkeypatch):
    md = sd.MatchDecision(sd.MARKET_UNAVAILABLE, "over/under non modélisé", "PSG", "Lyon")
    monkeypatch.setattr(tools_mod, "decide_single", lambda h, a, m, **k: (md, None))
    out = json.loads(tools_mod.ev_analyze.invoke(
        {"home_team": "PSG", "away_team": "Lyon", "market": "over_2_5", "odds": 1.9}))
    assert out["status"] == sd.MARKET_UNAVAILABLE and out["decision"] == "ABSTAIN"


# ── Combos : refus tant que toutes les jambes ne sont pas BET ─────────────────
def _sel(decision):
    return sd.SelectionDecision("home", decision, 2.0, 0.5, (0.45, 0.55), 0.0, -0.1, 0.5, 0.0, ())


def test_parlay_abstains_if_any_leg_not_bet(monkeypatch):
    md_ok = sd.MatchDecision(sd.EVALUATED, "ok", "PSG", "Lyon")
    md_ab = sd.MatchDecision(sd.EVALUATED, "ok", "Arsenal", "Chelsea")
    calls = {"PSG": _sel("BET"), "Arsenal": _sel("ABSTAIN")}
    monkeypatch.setattr(tools_mod, "decide_single",
                        lambda h, a, m, **k: ((md_ok if h == "PSG" else md_ab), calls[h]))
    legs = json.dumps([{"home_team": "PSG", "away_team": "Lyon", "market": "home"},
                       {"home_team": "Arsenal", "away_team": "Chelsea", "market": "home"}])
    out = json.loads(tools_mod.parlay_analyze.invoke({"legs_json": legs}))
    assert out["combo_decision"] == "ABSTAIN"       # une jambe non-BET -> combiné refusé


def test_parlay_all_bet_routes_to_structured_builder(monkeypatch):
    md = sd.MatchDecision(sd.EVALUATED, "ok", "PSG", "Lyon")
    monkeypatch.setattr(tools_mod, "decide_single", lambda h, a, m, **k: (md, _sel("BET")))
    legs = json.dumps([{"home_team": "PSG", "away_team": "Lyon", "market": "home"},
                       {"home_team": "Arsenal", "away_team": "Chelsea", "market": "away"}])
    out = json.loads(tools_mod.parlay_analyze.invoke({"legs_json": legs}))
    assert out["combo_decision"] == "ALL_LEGS_BET"
    # Le pricing/sizing du combiné appartient EXCLUSIVEMENT au Combo Builder structuré.
    assert "axon recommend --allow-combos" in out["message"]
