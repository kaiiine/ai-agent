"""Orchestrateur sport live — hermétique, fausse gateway live injectée (zéro réseau).

Preuve : événement Winamax résolu + couvert -> vraie MarketPrediction + vraie
BettingDecision (ABSTAIN, BE-FR-011). Non couvert / insuffisant / stale ->
refus explicite auditable, jamais de probabilités fabriquées.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.quant.gateway.core.errors import NoDataAvailableError
from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
    evaluate_live_event,
)

_PSG = "team:football:fra:psg"
_OM = "team:football:fra:marseille"
_KICKOFF = datetime(2025, 10, 5, 17, tzinfo=timezone.utc)
_DECISION = datetime(2025, 10, 4, 12, tzinfo=timezone.utc)      # distinct du coup d'envoi
_DATES = ["2025-09-28", "2025-09-21", "2025-09-14", "2025-08-31", "2025-08-24"]


def _form(pairs):
    return [{"is_home": h, "goals_home": gh, "goals_away": ga,
             "opponent_id": f"o{i}", "date": _DATES[i], "league_id": "L", "season": "2025"}
            for i, (h, gh, ga) in enumerate(pairs)]


_PSG_FORM = _form([(True, 2, 0), (False, 3, 1), (True, 3, 0), (False, 2, 1), (True, 4, 1)])
_OM_FORM = _form([(True, 0, 2), (False, 0, 3), (True, 1, 2), (False, 0, 2), (True, 1, 1)])


class _FakeLiveGateway:
    def __init__(self, forms, standings, raise_exc=None):
        self._forms, self._standings, self._raise = forms, standings, raise_exc

    def recent_form(self, canonical_team_id, last, season):
        if self._raise:
            raise self._raise
        if canonical_team_id not in self._forms:
            raise NoDataAvailableError(canonical_team_id)
        return self._forms[canonical_team_id][:last]

    def standings_strength(self, league_canonical_id, season):
        if self._raise:
            raise self._raise
        return dict(self._standings)


def _resolver():
    identity = IdentityResolver([
        CanonicalEntity(_PSG, "Paris Saint Germain", ["PSG", "Paris SG", "Paris Saint-Germain"], {}),
        CanonicalEntity(_OM, "Marseille", ["OM"], {}),
    ])
    comp = lambda tid: (("competition:football:fra:ligue1", "RESOLVED", "competition_table")
                        if tid == "4" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _1x2_market():
    return RawMarket(
        market_type=MarketType.MATCH_WINNER, raw_bet_type=3178, raw_label="Résultat",
        template="3way", is_live=False, special_bet_value="type=prematch",
        selections=[RawSelection("1", "PSG", 1.75, "slot_1"),
                    RawSelection("x", "Match nul", 3.4, "draw"),
                    RawSelection("2", "OM", 4.20, "slot_2")],
    )


def _event(markets=None, sport="football", slot_1="Paris Saint-Germain", slot_2="Marseille"):
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="E1", sport=sport, competition="Ligue 1",
        slot_1_name=slot_1, slot_2_name=slot_2, slot_1_id="1", slot_2_id="2",
        start_time=_KICKOFF, status="PREMATCH", is_outright=False,
        markets=[_1x2_market()] if markets is None else markets,
        fetched_at=_DECISION, raw_tournament_id="4",
    )


_COVERED = lambda comp, season, dt: ["football_data_org"]
_NOT_COVERED = lambda comp, season, dt: []


def _run(gateway, *, event=None, coverage=_COVERED, freshness_probe=None):
    return evaluate_live_event(
        event or _event(), decision_time=_DECISION, event_resolver=_resolver(),
        sports_gateway=gateway, coverage_check=coverage, freshness_probe=freshness_probe,
    )


def _full_gateway():
    return _FakeLiveGateway({_PSG: _PSG_FORM, _OM: _OM_FORM}, {_PSG: 1.3, _OM: 0.7})


# ── Preuve : vraie prédiction + vraie décision (ABSTAIN) ──────────────────────
def test_nominal_produces_real_prediction_and_abstain_decision():
    res = _run(_full_gateway())
    assert res.status is S.EVALUATED
    assert set(res.predictions) == {"home", "draw", "away"}
    assert len(res.decisions) == 3
    assert all(d.decision == "ABSTAIN" and "MODEL_NOT_SUPPORTED" in d.reasons for d in res.decisions)
    assert res.feature_set is not None and res.canonical_event is not None
    # vraie probabilité, pas fabriquée
    assert 0.0 < res.predictions["home"].fair_probability < 1.0


# ── decision_time injecté, capturé une fois ───────────────────────────────────
def test_as_of_equals_decision_time_not_scheduled_at():
    res = _run(_full_gateway())
    assert res.feature_set.as_of == _DECISION
    assert res.feature_set.as_of != _KICKOFF
    assert all(p.point_in_time == _DECISION for p in res.predictions.values())


# ── Fraîcheur inconnue : warning dans LES DEUX endroits ───────────────────────
def test_freshness_unavailable_warning_in_result_and_prediction():
    res = _run(_full_gateway())                                # pas de freshness_probe
    assert any("freshness_unavailable" in w for w in res.warnings)
    for pred in res.predictions.values():
        assert any("freshness_unavailable" in w for w in pred.explanation.warnings)


def test_stale_under_threshold_evaluates():
    res = _run(_full_gateway(), freshness_probe=lambda: timedelta(hours=12))
    assert res.status is S.EVALUATED
    assert not any("freshness_unavailable" in w for w in res.warnings)   # probe fourni


def test_data_too_stale_refuses():
    res = _run(_full_gateway(), freshness_probe=lambda: timedelta(hours=72))   # > 48h
    assert res.status is S.DATA_TOO_STALE
    assert res.predictions == {}
    assert res.feature_set is not None


# ── Refus explicites, jamais de probabilités fabriquées ───────────────────────
def test_sport_not_supported():
    res = _run(_full_gateway(), event=_event(sport="handball"))
    assert res.status is S.SPORT_NOT_SUPPORTED
    assert res.predictions == {}


def test_event_not_resolved():
    res = _run(_full_gateway(), event=_event(slot_1="Copenhague"))    # inconnu
    assert res.status is S.EVENT_NOT_RESOLVED
    assert res.predictions == {}


def test_no_1x2_market_is_canonicalization_failed():
    res = _run(_full_gateway(), event=_event(markets=[]))
    assert res.status is S.MARKET_CANONICALIZATION_FAILED


def test_competition_not_covered():
    res = _run(_full_gateway(), coverage=_NOT_COVERED)
    assert res.status is S.COMPETITION_NOT_COVERED
    assert res.feature_set is None and res.predictions == {}


def test_gateway_unavailable_keeps_exception_context():
    gw = _FakeLiveGateway({}, {}, raise_exc=ConnectionError("timeout"))
    res = _run(gw)
    assert res.status is S.GATEWAY_UNAVAILABLE
    assert res.error_context["type"] == "ConnectionError"
    assert res.predictions == {}


def test_insufficient_features_when_one_team_has_no_form():
    gw = _FakeLiveGateway({_PSG: _PSG_FORM}, {_PSG: 1.3, _OM: 0.7})   # OM sans forme -> NoData avalé
    res = _run(gw)
    assert res.status is S.INSUFFICIENT_FEATURES
    assert res.feature_set is not None            # features construites (dégradées)
    assert res.predictions == {}                  # aucune prédiction fabriquée


# ── Fraîcheur live CÂBLÉE : Gateway calcule -> BE lit (jamais recalculée) ──────
from src.agents.quant.gateway.gateway import DataFreshness           # noqa: E402
from src.agents.quant.betting_engine.live_evaluation import (        # noqa: E402
    _FRESHNESS_DEGRADED,
    _FRESHNESS_UNAVAILABLE,
)


class _FreshGateway(_FakeLiveGateway):
    """Gateway live exposant `data_freshness` (capacité de fraîcheur réelle)."""
    def __init__(self, freshness):
        super().__init__({_PSG: _PSG_FORM, _OM: _OM_FORM}, {_PSG: 1.3, _OM: 0.7})
        self._freshness = freshness
        self.freshness_calls = []

    def data_freshness(self, league_canonical_id, season, data_type="RESULTS"):
        self.freshness_calls.append((league_canonical_id, season, data_type))
        return self._freshness


def _df(effective_time, *, basis="published_time", degraded=False):
    return DataFreshness(freshness_score=0.9, effective_time=effective_time,
                         basis=basis, degraded=degraded, stale=False)


def test_live_freshness_from_gateway_recent_evaluates():
    gw = _FreshGateway(_df(_DECISION - timedelta(hours=2)))            # 2h < tolérance 48h
    res = _run(gw)
    assert res.status is S.EVALUATED
    # Provenance : la Gateway a bien été interrogée pour la compétition résolue.
    assert gw.freshness_calls == [("competition:football:fra:ligue1", "2025", "RESULTS")]
    # Fraîcheur mesurée et suffisante -> aucune note d'indispo/dégradation.
    assert _FRESHNESS_UNAVAILABLE not in res.warnings
    assert _FRESHNESS_DEGRADED not in res.warnings


def test_live_freshness_from_gateway_stale_refuses():
    gw = _FreshGateway(_df(_DECISION - timedelta(hours=100)))          # 100h > tolérance 48h
    res = _run(gw)
    assert res.status is S.DATA_TOO_STALE                              # décision explicite
    assert res.predictions == {}                                      # aucune prédiction servie


def test_live_freshness_degraded_is_not_measurable_no_invented_score():
    # Repli sur fetched_at (degraded) : même si fetched_at est TRÈS récent, on ne
    # convertit pas ça en "frais" -> staleness non mesurable, note explicite.
    gw = _FreshGateway(_df(_DECISION, basis="fetched_at", degraded=True))
    res = _run(gw)
    assert res.status is S.EVALUATED
    assert _FRESHNESS_DEGRADED in res.warnings                        # jamais un score favorable inventé
    assert all(_FRESHNESS_DEGRADED in p.explanation.warnings for p in res.predictions.values())


def test_live_freshness_missing_data_is_not_measurable():
    gw = _FreshGateway(None)                                          # aucune donnée de fraîcheur
    res = _run(gw)
    assert res.status is S.EVALUATED
    assert _FRESHNESS_DEGRADED in res.warnings                        # non mesurable, pas "frais"


def test_gateway_without_data_freshness_is_unavailable():
    # Gateway sans capacité de fraîcheur -> warning d'indisponibilité (comportement historique).
    res = _run(_full_gateway())
    assert res.status is S.EVALUATED
    assert _FRESHNESS_UNAVAILABLE in res.warnings


def test_injected_probe_overrides_gateway_capability():
    # Une sonde explicite (test) a priorité sur la capacité Gateway.
    gw = _FreshGateway(_df(_DECISION - timedelta(hours=2)))
    res = _run(gw, freshness_probe=lambda: timedelta(hours=100))       # forcée trop vieille
    assert res.status is S.DATA_TOO_STALE
    assert gw.freshness_calls == []                                    # capacité Gateway non appelée


# ── Money-path SUPPORTED end-to-end (§16 : module SYNTHÉTIQUE, jamais le ledger réel)
from src.agents.quant.betting_engine.core.feature_set import EventFeatureSet    # noqa: E402
from src.agents.quant.betting_engine.core.market_model import (                  # noqa: E402
    DataReadiness, MarketPrediction, PredictionExplanation, UncertaintyStatus,
)


class _SupportedModel:
    """Modèle SYNTHÉTIQUE de test, explicitement SUPPORTED avec intervalle ESTIMÉ.
    Ne touche NI le ledger réel NI la politique de maturité (seam sport_modules)."""
    def assess_data_readiness(self, event, features):
        return DataReadiness.SUPPORTED

    def predict_selections(self, event, features, point_in_time):
        def mk(sel, low, fair, high):
            return MarketPrediction(
                "football", "MATCH_WINNER", sel, fair, low, high, UncertaintyStatus.ESTIMATED,
                "synthetic.supported.v1", 1.0, DataReadiness.SUPPORTED, point_in_time,
                PredictionExplanation([], set(), [], []))
        # home a une vraie borne basse rentable (0.60·1.75−1 = 0.05 ≥ min_bet_ev).
        return {"home": mk("home", 0.60, 0.63, 0.66),
                "draw": mk("draw", 0.20, 0.22, 0.24),
                "away": mk("away", 0.14, 0.15, 0.16)}


class _SupportedModule:
    model = _SupportedModel()

    def build_feature_set(self, event, gateway, as_of):
        return EventFeatureSet(
            event_id=event.event_id, sport="football", as_of=as_of,
            feature_set_version="synthetic-1.0", event_features={},
            participant_features={}, matchup_features={}, missing_features=set())


def _run_supported(gateway, *, freshness_probe=None):
    return evaluate_live_event(
        _event(), decision_time=_DECISION, event_resolver=_resolver(),
        sports_gateway=gateway, coverage_check=_COVERED, freshness_probe=freshness_probe,
        sport_modules={"football": _SupportedModule()},
    )


def test_supported_admissible_opportunity_reaches_bet_no_notimplemented():
    res = _run_supported(_full_gateway())
    assert res.status is S.EVALUATED                                   # money-path atteint, aucune exception
    decisions = {d.selection: d for d in res.decisions}
    assert decisions["home"].decision == "BET"                         # opportunité admissible -> BET
    assert decisions["home"].reasons == []
    assert decisions["home"].worst_case_ev is not None                 # économie exposée (sizing = Advisor)
    assert "MODEL_NOT_SUPPORTED" not in decisions["home"].reasons


def test_supported_but_stale_abstains_before_money_path():
    gw = _FreshGateway(_df(_DECISION - timedelta(hours=100)))          # 100h > tolérance
    res = _run_supported(gw)
    assert res.status is S.DATA_TOO_STALE                              # gate data AVANT tout BET
    assert res.decisions == ()                                         # money-path jamais atteint
