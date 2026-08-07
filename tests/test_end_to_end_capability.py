"""CAPACITÉ système, bout en bout, HERMÉTIQUE (aucun réseau, aucune donnée inventée).

Démontre le chemin complet avec un modèle SUPPORTED de TEST (jamais le ledger réel,
jamais le statut du modèle réel) :

    connecteur synthétique -> evaluate_live_batch (BE) -> module SUPPORTED de test
    -> BET (BE-FR-012) -> adapt_live_batch -> pipeline Advisor -> RECOMMENDED
    -> CLI (axon recommend) -> audit persistant -> replay exact identique.

Distinction essentielle (exigée) :
  * CAPACITÉ : démontrable ici avec un SUPPORTED synthétique ;
  * ACTIVATION réelle : interdite tant que le modèle réel reste EXPERIMENTAL
    (garantie par test_maturity_policy + test_support_status_integration, inchangés).
Ce test ne promeut aucun modèle réel et ne touche ni la maturity policy ni le ledger.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import partial

from src.agents.quant.advisor.audit import JsonlAuditStore, replay_exact
from src.agents.quant.advisor.cli import main as cli_main
from src.agents.quant.advisor.domain.recommendations import RecommendationResponse  # noqa: F401
from src.agents.quant.advisor.domain.requests import OddsRange, RecommendationRequest
from src.agents.quant.advisor.domain.enums import MaturityPolicy, RecommendationOutcome, RiskProfile
from src.agents.quant.advisor.input_adapter.betting_engine_adapter import adapt_live_batch
from src.agents.quant.advisor.pipeline import run_pipeline
from src.agents.quant.advisor.cli import _load_configs
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.core.feature_set import EventFeatureSet
from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness, MarketPrediction, PredictionExplanation, UncertaintyStatus,
)
from src.agents.quant.betting_engine.live_batch import evaluate_live_batch
from src.agents.quant.betting_engine.live_evaluation import evaluate_live_event
from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver
from src.agents.quant.gateway.gateway import DataFreshness

_PSG = "team:football:fra:psg"
_OM = "team:football:fra:marseille"
_KICKOFF = datetime(2025, 10, 5, 17, tzinfo=timezone.utc)
_DECISION = datetime(2025, 10, 4, 12, tzinfo=timezone.utc)


# ── Modèle SUPPORTED SYNTHÉTIQUE (seam sport_modules ; jamais le ledger réel) ──
class _SupportedModel:
    def assess_data_readiness(self, event, features):
        return DataReadiness.SUPPORTED

    def predict_selections(self, event, features, point_in_time):
        def mk(sel, low, fair, high):
            return MarketPrediction(
                "football", "MATCH_WINNER", sel, fair, low, high, UncertaintyStatus.ESTIMATED,
                "synthetic.supported.v1", 1.0, DataReadiness.SUPPORTED, point_in_time,
                PredictionExplanation([], set(), [], []))
        return {"home": mk("home", 0.62, 0.65, 0.68),     # borne basse rentable @ 1.75
                "draw": mk("draw", 0.18, 0.20, 0.22),
                "away": mk("away", 0.12, 0.14, 0.16)}


class _SupportedModule:
    model = _SupportedModel()

    def build_feature_set(self, event, gateway, as_of):
        return EventFeatureSet(
            event_id=event.event_id, sport="football", as_of=as_of,
            feature_set_version="synthetic-1.0", event_features={},
            participant_features={}, matchup_features={}, missing_features=set())


def _raw_event() -> RawBookmakerEvent:
    market = RawMarket(
        market_type=MarketType.MATCH_WINNER, raw_bet_type=3178, raw_label="Résultat",
        template="3way", is_live=False, special_bet_value="type=prematch",
        selections=[RawSelection("1", "PSG", 1.75, "slot_1"),
                    RawSelection("x", "Match nul", 3.40, "draw"),
                    RawSelection("2", "OM", 4.20, "slot_2")])
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id="E2E-1", sport="football", competition="Ligue 1",
        slot_1_name="Paris Saint-Germain", slot_2_name="Marseille", slot_1_id="1", slot_2_id="2",
        start_time=_KICKOFF, status="PREMATCH", is_outright=False, markets=[market],
        fetched_at=_DECISION, raw_tournament_id="4")


class _Connector:
    def scan_catalog(self, sport):
        # Le batch scanne les SEPT sports enregistrés : ne rendre l'événement que
        # pour le sien, sinon il est évalué sept fois.
        return [e for e in [_raw_event()] if e.sport == sport]


class _FreshGateway:
    """Gateway de test exposant une fraîcheur RÉCENTE mesurée (le module SUPPORTED
    ignore les features ; seule la sonde de fraîcheur interroge cette gateway)."""
    def __init__(self, effective_time):
        self._effective = effective_time

    def data_freshness(self, league_canonical_id, season, data_type="RESULTS"):
        return DataFreshness(freshness_score=0.9, effective_time=self._effective,
                             basis="published_time", degraded=False, stale=False)


def _resolver():
    identity = IdentityResolver([
        CanonicalEntity(_PSG, "Paris Saint Germain", ["PSG", "Paris SG", "Paris Saint-Germain"], {}),
        CanonicalEntity(_OM, "Marseille", ["OM", "Olympique de Marseille"], {})])
    comp = lambda ev: (("competition:football:fra:ligue1", "RESOLVED", "competition_table")
                        if ev.raw_tournament_id == "4" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _adapted_batch():
    gateway = _FreshGateway(effective_time=_DECISION - timedelta(hours=1))
    evaluate = partial(
        evaluate_live_event,
        sport_modules={"football": _SupportedModule()},
        coverage_check=lambda comp, season, dt: ["football_data_org"])   # couverture stubbée
    batch = evaluate_live_batch(
        _Connector(), sports_gateway=gateway, event_resolver=_resolver(),
        evaluate=evaluate, now_fn=lambda: _DECISION)
    return adapt_live_batch(batch)


def _request(rid="req:e2e") -> RecommendationRequest:
    return RecommendationRequest(
        request_id=rid, decision_time=_DECISION, bankroll=Decimal("100"),
        currency="EUR", allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None,
        allowed_market_types=None, target_total_odds=OddsRange(Decimal("1.50"), Decimal("5.00")),
        max_total_stake=None, max_selections=1, max_portfolios=1, allow_singles=True,
        allow_combos=False, max_combo_legs=2, risk_profile=RiskProfile.BALANCED,
        maturity_policy=MaturityPolicy.SUPPORTED_ONLY, ranking_profile="balanced_v1",
        excluded_event_ids=frozenset(), excluded_participant_ids=frozenset(),
        excluded_market_types=frozenset())


# ── 1) BE -> BET -> adaptation fidèle ─────────────────────────────────────────
def test_supported_batch_yields_bet_candidate_via_adapter():
    adapted = _adapted_batch()
    homes = [e for e in adapted.evaluations if e.selection == "home"]
    assert len(homes) == 1
    home = homes[0]
    assert home.model_maturity == "SUPPORTED"
    assert home.decision == "BET"                              # money-path (BE-FR-012)
    assert home.calibration_score is not None                 # model_reliability exposée (0.75)


# ── 2) Pipeline Advisor -> RECOMMENDED ────────────────────────────────────────
def test_pipeline_recommends_a_bet():
    result = run_pipeline(_adapted_batch(), _request(), **_load_configs())
    resp = result.recommendation
    assert resp.outcome is RecommendationOutcome.RECOMMENDED
    assert resp.portfolios and resp.portfolios[0].total_stake > 0
    assert resp.portfolios[0].lines[0].legs[0].selection == "home"


# ── 3) CLI -> audit persistant -> replay exact identique ──────────────────────
def test_cli_end_to_end_audit_and_exact_replay(tmp_path):
    adapted = _adapted_batch()
    store = JsonlAuditStore(tmp_path / "audit.jsonl")
    code = cli_main(
        ["--bankroll", "100", "--currency", "EUR", "--risk", "balanced",
         "--maturity", "supported-only", "--target-odds-min", "1.50",
         "--target-odds-max", "5.00", "--format", "json", "--request-id", "req:e2e"],
        batch_loader=lambda dt: adapted, now_fn=lambda: _DECISION, audit_store=store)
    assert code == 0                                          # RECOMMENDED/REVIEW -> 0

    # Un seul enregistrement persisté ; on le relit et on rejoue à l'identique.
    records = list(store.iter_records())
    assert len(records) == 1
    envelope = store.get(records[0]["audit_id"])
    replayed = replay_exact(envelope)
    assert replayed.matches is True                           # replay MÉTIER identique
    assert replayed.differences == ()


def test_capability_does_not_touch_real_model_status():
    """Garde-fou : la démonstration de capacité ne promeut JAMAIS le modèle réel."""
    from src.agents.quant.betting_engine.assessment import assess_default_one_x_two
    assert assess_default_one_x_two().decision.status == "EXPERIMENTAL"
