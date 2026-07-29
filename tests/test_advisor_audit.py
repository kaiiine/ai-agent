"""Audit persistant & replay exact (Lot 10). Sérialisation canonique + checksum,
identité/idempotence, snapshots autonomes, round-trip, quatre états Combo,
corruption, frontière métier gelée, replay offline, unicité request_id (§0).
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import fields, replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.advisor import cli
from src.agents.quant.advisor.audit import (
    JsonlAuditStore, ReplayResult, build_config_snapshots, build_envelope,
    load_audit_config, replay_exact,
)
from src.agents.quant.advisor.audit import canonical, identity
from src.agents.quant.advisor.audit.errors import (
    AuditChecksumMismatch, AuditIncomplete, AuditNotFound, ConfigSnapshotCorrupt,
    DuplicateAuditDivergent, InvalidAuditJson, RequestIdContentMismatch,
    UnknownAuditSchemaVersion,
)
from src.agents.quant.advisor.audit.schema import (
    ComboBookmakerAcceptanceStatus, ComboMaterializationStatus,
)
from src.agents.quant.advisor.audit.snapshots import reconstruct_configs
from src.agents.quant.advisor.domain.enums import MaturityPolicy, RiskProfile
from src.agents.quant.advisor.domain.recommendations import RecommendationResponse
from src.agents.quant.advisor.domain.requests import OddsRange, RecommendationRequest
from src.agents.quant.advisor.input_adapter.schema import (
    AdaptedBatch, AdaptedEvaluation, AdaptedExplanation,
)
from src.agents.quant.advisor.pipeline import run_pipeline
from src.agents.quant.advisor.policy import load_policy_config
from src.agents.quant.advisor.policy import reason_codes as R
from src.agents.quant.advisor.ranking import load_ranking_profiles
from src.agents.quant.advisor.recommendation import load_sizing_profiles
from src.agents.quant.advisor.portfolio import load_portfolio_caps
from src.agents.quant.advisor.combos import load_combo_policy

_DEC = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
_KO = datetime(2026, 8, 1, 17, tzinfo=timezone.utc)
_NOW = datetime(2026, 7, 29, 15, tzinfo=timezone.utc)
_CFG = dict(policy_config=load_policy_config(), ranking_profiles=load_ranking_profiles(),
            sizing_profiles=load_sizing_profiles(), portfolio_caps=load_portfolio_caps(),
            combo_policy=load_combo_policy())


def _adapted(event="e1", participants=("a1", "a2"), odds=Decimal("2.50"), p_low=Decimal("0.60")):
    return AdaptedEvaluation(
        schema_version="1", event_id=event, sport="football", competition_id="comp:1",
        scheduled_at=_KO, participant_ids=participants, observed_at=_DEC, bookmaker="winamax",
        market_id=f"winamax:{event}:MATCH_WINNER", market_type="MATCH_WINNER", selection="home",
        bookmaker_odds=odds, fair_probability=Decimal("0.65"), probability_low=p_low,
        probability_high=Decimal("0.65"), uncertainty_status="ESTIMATED", model_version="m.v1",
        model_maturity="SUPPORTED", data_quality=Decimal("1.0"), calibration_score=None,
        freshness_score=Decimal("0.90"), liquidity_score=None, implied_probability_raw=Decimal("0.40"),
        no_vig_probability=Decimal("0.42"), edge=Decimal("0.20"), expected_value=Decimal("0.5"),
        is_boosted=False, decision="ABSTAIN", decision_reasons=("MODEL_NOT_SUPPORTED",), warnings=(),
        explanation=AdaptedExplanation((("form", 1.2),), frozenset(), ("home",), ()),
        source_decision_id=None)


def _batch(*evs, decision_time=_DEC):
    return AdaptedBatch("1", decision_time, tuple(evs), ())


def _request(request_id="r1", allow_combos=False):
    return RecommendationRequest(
        request_id=request_id, decision_time=_DEC, bankroll=Decimal("100"), currency="EUR",
        allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None,
        allowed_market_types=None, target_total_odds=OddsRange(Decimal("2.00"), Decimal("8.00")),
        max_total_stake=Decimal("100"), max_selections=5, max_portfolios=3, allow_singles=True,
        allow_combos=allow_combos, max_combo_legs=2, risk_profile=RiskProfile.BALANCED,
        maturity_policy=MaturityPolicy.SUPPORTED_ONLY, ranking_profile="balanced_v1",
        excluded_event_ids=frozenset(), excluded_participant_ids=frozenset(),
        excluded_market_types=frozenset())


def _envelope(request=None, batch=None):
    req = request or _request()
    b = batch or _batch(_adapted())
    snaps = build_config_snapshots(allow_combos=req.allow_combos)
    res = run_pipeline(b, req, **_CFG)
    return build_envelope(req, b, snaps, res.trace, res.recommendation, now=_NOW)


# ── §23 Sérialisation / checksum ──────────────────────────────────────────────
def test_checksum_deterministic():
    assert _envelope().payload_checksum == _envelope().payload_checksum


def test_mapping_order_independent_same_checksum():
    assert canonical.checksum({"a": 1, "b": 2}) == canonical.checksum({"b": 2, "a": 1})


def test_decimal_serialized_as_string():
    assert canonical.canonical_serialize(Decimal("2.10")) == '"2.10"'


def test_payload_tamper_detected_on_read(tmp_path):
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    store.append(_envelope())
    raw = json.loads((tmp_path / "a.jsonl").read_text().splitlines()[0])
    raw["payload"]["be_run_id"] = "TAMPERED"                # payload modifié, checksum inchangé
    (tmp_path / "a.jsonl").write_text(json.dumps(raw) + "\n")
    with pytest.raises(AuditChecksumMismatch):
        store.get(raw["audit_id"])


# ── §24 Identité / idempotence ────────────────────────────────────────────────
def test_same_request_same_fingerprint_and_audit_id():
    a, b = _request("r1"), _request("r1")
    assert identity.request_fingerprint(a) == identity.request_fingerprint(b)
    assert _envelope(a).audit_id == _envelope(b).audit_id


def test_idempotent_append(tmp_path):
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    env = _envelope()
    store.append(env)
    store.append(env)                                       # idempotent no-op
    assert len((tmp_path / "a.jsonl").read_text().splitlines()) == 1


def test_request_id_content_mismatch(tmp_path):
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    store.append(_envelope(_request("r1")))
    other = replace(_request("r1"), currency="USD")         # même request_id, contenu métier différent
    with pytest.raises(RequestIdContentMismatch):
        store.append(_envelope(other))


def test_different_request_id_same_content_different_audit_id():
    assert _envelope(_request("r1")).audit_id != _envelope(_request("r2")).audit_id


def test_duplicate_audit_divergent(tmp_path):
    # Même requête (donc même audit_id) mais payload différent (batch différent).
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    store.append(_envelope(_request("r1"), _batch(_adapted("e1"))))
    with pytest.raises(DuplicateAuditDivergent):
        store.append(_envelope(_request("r1"), _batch(_adapted("e2"))))


def test_created_at_does_not_break_idempotence(tmp_path):
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    req, b = _request(), _batch(_adapted())
    snaps = build_config_snapshots(allow_combos=False)
    res = run_pipeline(b, req, **_CFG)
    e1 = build_envelope(req, b, snaps, res.trace, res.recommendation, now=_NOW)
    e2 = build_envelope(req, b, snaps, res.trace, res.recommendation,
                        now=datetime(2027, 1, 1, tzinfo=timezone.utc))   # created_at différent
    store.append(e1)
    store.append(e2)                                        # idempotent malgré created_at
    assert len((tmp_path / "a.jsonl").read_text().splitlines()) == 1


# ── §25 Snapshots de config ───────────────────────────────────────────────────
def test_snapshots_archive_full_content():
    env = _envelope()
    names = {s.config_name for s in env.payload.config_snapshots}
    assert {"eligibility_policy", "ranking_profiles", "sizing_policy", "portfolio_policy"} <= names
    for s in env.payload.config_snapshots:
        assert s.content and canonical.checksum(s.content) == s.checksum


def test_reconstruct_uses_archived_content_not_current_file(tmp_path):
    # Snapshot dont le contenu diffère du fichier courant -> config reconstruite
    # reflète l'ARCHIVE, jamais le disque.
    env = _envelope()
    snaps = [dict(config_name=s.config_name, content=dict(s.content), checksum=s.checksum)
             for s in env.payload.config_snapshots]
    elig = next(s for s in snaps if s["config_name"] == "eligibility_policy")
    elig["content"]["profiles"]["BALANCED"]["min_data_quality"] = "0.99"   # contenu modifié
    elig["checksum"] = canonical.checksum(elig["content"])                 # checksum recalculé
    cfg = reconstruct_configs(snaps, tmp_path)
    assert cfg["policy_config"].profile_for(RiskProfile.BALANCED).min_data_quality == Decimal("0.99")


def test_corrupt_snapshot_rejected(tmp_path):
    env = _envelope()
    snaps = [dict(config_name=s.config_name, content=dict(s.content), checksum=s.checksum)
             for s in env.payload.config_snapshots]
    snaps[0]["content"] = {"tampered": True}               # contenu ≠ checksum
    with pytest.raises(ConfigSnapshotCorrupt):
        reconstruct_configs(snaps, tmp_path)


# ── §26 Round-trip + §30 replay offline ──────────────────────────────────────
def test_round_trip_and_exact_replay(tmp_path):
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    env = _envelope(_request("r1"), _batch(_adapted("e1"), _adapted("e2", ("b1", "b2"))))
    store.append(env)
    raw = store.get(env.audit_id)                          # lu + validé
    result = replay_exact(raw)                             # rejeu offline (aucun BE/gateway)
    assert isinstance(result, ReplayResult)
    assert result.matches and result.differences == ()


def test_replay_detects_divergent_recommendation():
    # Résultat métier divergent -> matches=False, différence exposée (aucun filtre opportuniste).
    raw = json.loads(canonical.canonical_serialize(_envelope()))
    raw["payload"]["recommendation"]["outcome"] = "NO_OPPORTUNITY"
    result = replay_exact(raw)
    assert not result.matches and "recommendation" in result.differences


def test_replay_detects_divergent_score():
    # Un SCORE de ranking archivé divergent (§16) -> exposé dans differences.
    raw = json.loads(canonical.canonical_serialize(_envelope()))
    assert raw["payload"]["ranked_evaluations"], "fixture doit produire un ELIGIBLE classé"
    raw["payload"]["ranked_evaluations"][0]["ranking_score"] = "999"
    result = replay_exact(raw)
    assert not result.matches and "ranked_evaluations" in result.differences


# ── §27 Quatre états Combo (archivés explicitement) ───────────────────────────
def _combos(env):
    return env.payload.combos


def test_combo_state_not_searched():
    c = _combos(_envelope(_request(allow_combos=False)))
    assert c.builder_invoked is False
    assert c.materialization_status is ComboMaterializationStatus.NOT_APPLICABLE


def test_combo_state_no_admissible():
    # allow_combos=True mais deux legs du MÊME événement -> STRUCTURALLY_DEPENDENT -> aucun admissible.
    env = _envelope(_request(allow_combos=True), _batch(_adapted("e1", ("a1", "a2")),
                                                        _adapted("e1", ("a1", "a2"))))
    c = _combos(env)
    assert c.builder_invoked is True and c.admissible_count == 0
    assert c.materialization_status is ComboMaterializationStatus.NO_CANDIDATE


def test_combo_state_admissible_blocked_sizing_and_survives_replay(tmp_path):
    env = _envelope(_request(allow_combos=True),
                    _batch(_adapted("e1", ("a1", "a2")), _adapted("e2", ("b1", "b2"))))
    c = _combos(env)
    assert c.admissible_count > 0
    assert c.bookmaker_acceptance_status is ComboBookmakerAcceptanceStatus.NOT_VERIFIED
    assert c.materialization_status is ComboMaterializationStatus.BLOCKED_SIZING_NOT_AVAILABLE
    assert c.combo_signal == R.COMBO_SIZING_NOT_AVAILABLE
    # aucune PortfolioLine COMBO
    for pf in env.payload.recommendation.portfolios:
        for line in pf.lines:
            assert line.line_type.value == "SINGLE"
    # survit au round-trip + replay
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    store.append(env)
    assert replay_exact(store.get(env.audit_id)).matches


# ── §28 Corruption / erreurs ──────────────────────────────────────────────────
def test_invalid_json_line(tmp_path):
    (tmp_path / "a.jsonl").write_text("{not json\n")
    with pytest.raises(InvalidAuditJson):
        JsonlAuditStore(tmp_path / "a.jsonl").get("x")


def test_unknown_schema_version(tmp_path):
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    env = _envelope()
    store.append(env)
    raw = json.loads((tmp_path / "a.jsonl").read_text().splitlines()[0])
    raw["audit_schema_version"] = "999"
    (tmp_path / "a.jsonl").write_text(json.dumps(raw) + "\n")
    with pytest.raises(UnknownAuditSchemaVersion):
        store.get(raw["audit_id"])


def test_incomplete_audit(tmp_path):
    (tmp_path / "a.jsonl").write_text(json.dumps({"audit_id": "x"}) + "\n")
    with pytest.raises(AuditIncomplete):
        JsonlAuditStore(tmp_path / "a.jsonl").get("x")


def test_audit_not_found(tmp_path):
    with pytest.raises(AuditNotFound):
        JsonlAuditStore(tmp_path / "a.jsonl").get("absent")


# ── §29 Frontière métier gelée ────────────────────────────────────────────────
def test_recommendation_response_contract_unchanged():
    names = {f.name for f in fields(RecommendationResponse)}
    assert names == {"request_id", "generated_at", "outcome", "portfolios",
                     "review_candidates", "rejection_summary", "warnings", "audit_id"}


def test_config_default_and_no_user_path():
    cfg = load_audit_config()
    assert cfg.audit_store_path == "var/advisor/audits/audit.jsonl"
    assert "~" not in cfg.audit_store_path


# ── §0 Unicité de request_id (CLI génère un id frais) ─────────────────────────
def test_cli_generates_fresh_request_id():
    # uuid4 RÉEL (pas de mock) : deux invocations -> ids distincts, format contractuel.
    args = cli._build_parser().parse_args(["--bankroll", "100"])
    r1 = cli._build_request(args, _DEC)
    r2 = cli._build_request(args, _DEC)
    assert r1.request_id != r2.request_id and r1.request_id.startswith("req:")


def test_cli_request_id_propagated_unchanged_to_audit(tmp_path):
    store = JsonlAuditStore(tmp_path / "a.jsonl")
    loader = lambda dt: AdaptedBatch("1", dt, (_adapted(),), ())
    cli.main(["--bankroll", "100", "--request-id", "REQ-X"],
             batch_loader=loader, now_fn=lambda: _DEC, audit_store=store)
    records = list(store.iter_records())
    assert len(records) == 1 and records[0]["request_id"] == "REQ-X"   # propagé sans modification
