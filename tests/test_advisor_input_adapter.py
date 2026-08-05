"""Adaptateur Betting Engine -> input Advisor (Lot 2).

Vérifie : traduction fidèle d'une évaluation réelle, préservation de la maturité
et de l'explication, rejet de version/champ, aucun float monétaire, reconstruction
du market_id STRICTEMENT égale à l'identifiant canonique, provenance None (Q5),
événement non évaluable tracé sans candidat fabriqué, aucun recalcul.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
from src.agents.quant.betting_engine.bookmakers.market_canonicalizer import (
    canonicalize_market, resolve_participant_roles,
)
from src.agents.quant.betting_engine.bookmakers.protocol import (
    MarketType, RawBookmakerEvent, RawMarket, RawSelection,
)
from src.agents.quant.betting_engine.core.odds import OddsSnapshot
from src.agents.quant.betting_engine.live_batch import LiveEvaluationBatch
from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationResult, LiveEvaluationStatus as St, evaluate_live_event,
)
from src.agents.quant.betting_engine.value_engine.decision import evaluate_selection

from src.agents.quant.advisor.input_adapter import betting_engine_adapter as adapter
from src.agents.quant.advisor.input_adapter.errors import (
    IncompatibleSchemaError, MissingRequiredFieldError,
)
from src.agents.quant.advisor.input_adapter.schema import (
    INPUT_SCHEMA_VERSION, AdaptedEvaluation,
)

_PSG = "team:football:fra:psg"
_OM = "team:football:fra:marseille"
_KO = datetime(2025, 10, 5, 17, tzinfo=timezone.utc)
_DEC = datetime(2025, 10, 4, 12, tzinfo=timezone.utc)
_DATES = ["2025-09-28", "2025-09-21", "2025-09-14", "2025-08-31", "2025-08-24"]


# ── Fixtures : un événement FL1 réellement évaluable ──────────────────────────
def _form(pairs):
    return [{"is_home": h, "goals_home": gh, "goals_away": ga, "opponent_id": f"o{i}",
             "date": _DATES[i], "league_id": "L", "season": "2025"}
            for i, (h, gh, ga) in enumerate(pairs)]


class _FakeGateway:
    def __init__(self, forms, standings):
        self._forms, self._standings = forms, standings

    def recent_form(self, cid, *, competition_id, last, season):
        from src.agents.quant.gateway.core.errors import NoDataAvailableError
        if cid not in self._forms:
            raise NoDataAvailableError(cid)
        return self._forms[cid][:last]

    def standings_strength(self, comp, season):
        return dict(self._standings)


def _resolver():
    identity = IdentityResolver([
        CanonicalEntity(_PSG, "Paris Saint Germain", ["PSG", "Paris SG", "Paris Saint-Germain"], {}),
        CanonicalEntity(_OM, "Marseille", ["OM"], {}),
    ])
    comp = lambda tid: (("competition:football:fra:ligue1", "RESOLVED", "competition_table")
                        if tid == "4" else (None, "UNRESOLVED", "none"))
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _event(bem_id="E1", slot_1="Paris Saint-Germain"):
    market = RawMarket(MarketType.MATCH_WINNER, 3178, "Résultat", "3way", False, "type=prematch",
                       [RawSelection("1", "PSG", 1.75, "slot_1"),
                        RawSelection("x", "Nul", 3.4, "draw"),
                        RawSelection("2", "OM", 4.20, "slot_2")])
    return RawBookmakerEvent(
        bookmaker="winamax", bookmaker_event_id=bem_id, sport="football", competition="Ligue 1",
        slot_1_name=slot_1, slot_2_name="Marseille", slot_1_id="1", slot_2_id="2",
        start_time=_KO, status="PREMATCH", is_outright=False,
        markets=[market], fetched_at=_DEC, raw_tournament_id="4")


_COVERED = lambda comp, season, dt: ["football_data_org"]
_GW = lambda: _FakeGateway(
    {_PSG: _form([(True, 2, 0), (False, 3, 1), (True, 3, 0), (False, 2, 1), (True, 4, 1)]),
     _OM: _form([(True, 0, 2), (False, 0, 3), (True, 1, 2), (False, 0, 2), (True, 1, 1)])},
    {_PSG: 1.3, _OM: 0.7})


def _evaluated(bem_id="E1"):
    res = evaluate_live_event(_event(bem_id), decision_time=_DEC, event_resolver=_resolver(),
                              sports_gateway=_GW(), coverage_check=_COVERED)
    assert res.status is St.EVALUATED
    return res


def _refusal():
    res = evaluate_live_event(_event(slot_1="Copenhague"), decision_time=_DEC,
                              event_resolver=_resolver(), sports_gateway=_GW(), coverage_check=_COVERED)
    assert res.status is St.EVENT_NOT_RESOLVED
    return res


def _batch(*pairs):
    return LiveEvaluationBatch(decision_time=_DEC, results=tuple(pairs))


# ── Traduction d'une évaluation valide ────────────────────────────────────────
def test_adapts_a_valid_evaluation():
    out = adapter.adapt_live_batch(_batch((_event(), _evaluated())))
    assert out.schema_version == INPUT_SCHEMA_VERSION
    assert out.decision_time == _DEC                      # évaluations chargées POUR decision_time
    assert {e.selection for e in out.evaluations} == {"home", "draw", "away"}
    home = next(e for e in out.evaluations if e.selection == "home")
    assert home.event_id and home.competition_id == "competition:football:fra:ligue1"
    assert home.participant_ids == (_PSG, _OM)
    assert home.decision == "ABSTAIN" and "MODEL_NOT_SUPPORTED" in home.decision_reasons
    assert home.is_boosted is False
    assert out.skipped == ()


def test_observed_at_is_the_odds_fetch_time():
    # observed_at = RawBookmakerEvent.fetched_at (instant d'observation des cotes),
    # PAS le decision_time de la requête.
    raw = _event()
    out = adapter.adapt_live_batch(_batch((raw, _evaluated())))
    assert all(e.observed_at == raw.fetched_at for e in out.evaluations)


def test_market_maturity_preserved_not_upgraded():
    out = adapter.adapt_live_batch(_batch((_event(), _evaluated())))
    assert {e.model_maturity for e in out.evaluations} == {"EXPERIMENTAL"}   # jamais SUPPORTED


def test_explanation_is_preserved_and_no_warning_dropped():
    home = next(e for e in adapter.adapt_live_batch(_batch((_event(), _evaluated()))).evaluations
                if e.selection == "home")
    assert home.explanation.top_features                  # features réelles conservées
    # le warning de fraîcheur (ajouté par l'orchestrateur) est préservé jusqu'ici
    assert any(w.startswith("freshness_unavailable") for w in home.warnings)
    assert any(w.startswith("freshness_unavailable") for w in home.explanation.warnings)


# ── Rejets explicites ─────────────────────────────────────────────────────────
# Compatibilité RÉELLE : validation structurelle. Les trois tests suivants
# (canonical_event manquant, maturité inconnue, sélection absente via
# _adapt) sont le vrai garde-fou. `expected_schema` n'est qu'un épinglage
# interne côté adaptateur — PAS une version émise par le moteur.
def test_rejects_unsupported_expected_schema():
    """Épinglage INTERNE : l'adaptateur cible un schéma ; un appelant qui en
    exige un autre est rejeté. Ce n'est PAS une négociation avec une version
    émise par le Betting Engine (le moteur n'en émet aucune)."""
    with pytest.raises(IncompatibleSchemaError):
        adapter.adapt_live_batch(_batch((_event(), _evaluated())),
                                 expected_schema="betting-engine.live.v2")


def test_rejects_missing_required_field():
    # Compatibilité STRUCTURELLE : EVALUATED sans canonical_event -> échec explicite.
    broken = LiveEvaluationResult(
        status=St.EVALUATED, reason="ok", decision_time=_DEC,
        bookmaker_event_id="E1", canonical_event=None)
    with pytest.raises(MissingRequiredFieldError):
        adapter.adapt_result(_event(), broken)


def test_rejects_unknown_model_maturity():
    res = _evaluated()
    poisoned = {**res.predictions,
                "home": replace(res.predictions["home"],
                                calibration_status=SimpleNamespace(value="FUTURE_MATURITY"))}
    res = replace(res, predictions=poisoned)
    with pytest.raises(IncompatibleSchemaError):
        adapter.adapt_result(_event(), res)


# ── Aucun float monétaire résiduel ────────────────────────────────────────────
def test_no_residual_monetary_float():
    home = next(e for e in adapter.adapt_live_batch(_batch((_event(), _evaluated()))).evaluations
                if e.selection == "home")
    for name in ("bookmaker_odds", "fair_probability", "probability_low", "probability_high",
                 "data_quality", "implied_probability_raw", "no_vig_probability",
                 "edge", "expected_value"):
        value = getattr(home, name)
        assert value is not None and isinstance(value, Decimal), name
        assert not isinstance(value, float), name


# ── market_id : reconstruction == identifiant canonique (mandat Q5) ────────────
def test_market_id_equals_canonical_builder_output():
    raw = _event()
    mapping = _resolver().resolve_event(raw)
    role_resolution = resolve_participant_roles(raw)
    canon = canonicalize_market(raw, raw.markets[0], mapping, role_resolution)
    assert canon.market_id is not None

    out = adapter.adapt_live_batch(_batch((raw, _evaluated())))
    for e in out.evaluations:
        # STRICTEMENT l'identifiant produit par le canonicalizer — aucun format parallèle.
        assert e.market_id == canon.market_id


# ── Provenance non inventée (Q5) ──────────────────────────────────────────────
def test_source_decision_id_is_none():
    out = adapter.adapt_live_batch(_batch((_event(), _evaluated())))
    assert all(e.source_decision_id is None for e in out.evaluations)


# ── Score absent = None, JAMAIS 0 silencieux ──────────────────────────────────
def test_missing_scores_are_none_never_zero():
    home = next(e for e in adapter.adapt_live_batch(_batch((_event(), _evaluated()))).evaluations
                if e.selection == "home")
    # non exposés par la source : restent None (jamais convertis en 0 / Decimal(0))
    assert home.freshness_score is None
    assert home.liquidity_score is None
    assert home.calibration_score is None


# ── Frontière boosted : is_boosted=False ne peut PAS accompagner une offre boostée ──
def test_boosted_offer_never_adapted_as_standard_odds():
    """Verrouille la prémisse qui rend is_boosted=False factuellement correct.

    Une offre boostée n'est JAMAIS évaluée comme cote standard : le value_engine
    la refuse (NOT_EVALUATED + UNSUPPORTED_ODDS_TYPE). L'adaptateur la porte donc
    avec is_boosted=True et SANS métriques de valeur — jamais is_boosted=False.
    (La prémisse boosted->NOT_EVALUATED est aussi couverte par test_value_engine.)"""
    res = _evaluated()
    pred_home = res.predictions["home"]
    boosted = OddsSnapshot("ev:1", "MATCH_WINNER", "home", 2.5, _DEC, "winamax", is_boosted=True)
    boosted_home = evaluate_selection(pred_home, [boosted])       # vrai chemin moteur
    assert boosted_home.evaluation_status.value == "NOT_EVALUATED"
    assert "UNSUPPORTED_ODDS_TYPE" in boosted_home.reasons

    res = replace(res, decisions=tuple(
        boosted_home if d.selection == "home" else d for d in res.decisions))
    home = next(e for e in adapter.adapt_result(_event(), res)[0] if e.selection == "home")
    assert home.is_boosted is True                                 # jamais False pour une offre boostée
    assert home.no_vig_probability is None and home.implied_probability_raw is None


# ── Événement non évaluable : tracé, aucun candidat ───────────────────────────
def test_non_evaluated_result_is_skipped_not_candidate():
    out = adapter.adapt_live_batch(_batch((_event(slot_1="Copenhague"), _refusal())))
    assert out.evaluations == ()                          # aucun candidat fabriqué
    assert len(out.skipped) == 1
    assert out.skipped[0].status == "EVENT_NOT_RESOLVED"
    assert out.skipped[0].reason                           # raison tracée


# ── Aucun recalcul : les nombres viennent du moteur ───────────────────────────
def test_numbers_are_propagated_not_recomputed():
    res = _evaluated()
    home_decision = next(d for d in res.decisions if d.selection == "home")
    home = next(e for e in adapter.adapt_live_batch(_batch((_event(), res))).evaluations
                if e.selection == "home")
    # égalité exacte avec la sortie moteur (simple changement de type float->Decimal)
    assert home.bookmaker_odds == Decimal(str(home_decision.bookmaker_odds))
    assert home.expected_value == Decimal(str(home_decision.expected_value))
    assert home.edge == Decimal(str(home_decision.edge))


# ── Wiring : load_and_adapt consomme evaluate_live_batch (jamais le CLI) ───────
def test_load_and_adapt_consumes_the_domain_batch():
    def _catalogue(_connector):
        return [_event()]

    def _evaluate(event, **kw):
        return evaluate_live_event(event, coverage_check=_COVERED, **kw)

    out = adapter.load_and_adapt(
        object(), sports_gateway=_GW(), event_resolver=_resolver(),
        catalogue=_catalogue, evaluate=_evaluate, now_fn=lambda: _DEC)
    assert out.decision_time == _DEC
    assert len(out.evaluations) == 3                       # home/draw/away d'un événement évalué


def test_adapted_evaluation_is_frozen():
    home = next(e for e in adapter.adapt_live_batch(_batch((_event(), _evaluated()))).evaluations
                if e.selection == "home")
    assert isinstance(home, AdaptedEvaluation)
    with pytest.raises(Exception):
        home.selection = "away"        # type: ignore[misc]
