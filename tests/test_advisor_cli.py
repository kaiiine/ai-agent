"""CLI `axon recommend` (Lot 7) — hermétique : un faux `batch_loader` injecte un
`AdaptedBatch`, tout le pipeline Advisor tourne (génération→policy→ranking→reco).
Vérifie codes de sortie PRD §18.3, formats human/json, filtres, demande invalide.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

from src.agents.quant.advisor import cli
from src.agents.quant.advisor.audit import JsonlAuditStore

_REPO = pathlib.Path(__file__).resolve().parents[1]
from src.agents.quant.advisor.input_adapter.schema import (
    AdaptedBatch, AdaptedEvaluation, AdaptedExplanation,
)

# Store d'audit temporaire : le CLI persiste, mais les tests n'écrivent pas dans var/.
_AUDIT_STORE = JsonlAuditStore(pathlib.Path(tempfile.mkdtemp()) / "cli_audit.jsonl")

_DEC = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
_KO = datetime(2026, 8, 1, 17, tzinfo=timezone.utc)


def _adapted(maturity="SUPPORTED", sport="football", ev_ok=True, sel="home", event="e1") -> AdaptedEvaluation:
    p_low = Decimal("0.55") if ev_ok else Decimal("0.30")
    return AdaptedEvaluation(
        schema_version="1", event_id=event, sport=sport,
        competition_id="competition:football:fra:ligue1", scheduled_at=_KO,
        participant_ids=("team:a", "team:b"), observed_at=_DEC, bookmaker="winamax",
        market_id=f"winamax:{event}:MATCH_WINNER", market_type="MATCH_WINNER", selection=sel,
        bookmaker_odds=Decimal("2.10"), fair_probability=Decimal("0.57"),
        probability_low=p_low, probability_high=Decimal("0.60"), uncertainty_status="ESTIMATED",
        model_version="m.v1", model_maturity=maturity, data_quality=Decimal("1.0"),
        calibration_score=None, freshness_score=Decimal("0.90"), liquidity_score=None,
        implied_probability_raw=Decimal("0.4762"), no_vig_probability=Decimal("0.50"),
        edge=Decimal("0.07"), expected_value=Decimal("0.19"), is_boosted=False,
        decision="ABSTAIN", decision_reasons=("MODEL_NOT_SUPPORTED",), warnings=(),
        explanation=AdaptedExplanation((("form", 1.0),), frozenset(), ("home",), ()),
        source_decision_id=None)


def _loader(*evs):
    def load(decision_time):
        return AdaptedBatch("1", decision_time, tuple(evs), ())
    return load


def _run(argv, loader):
    return cli.main(argv, batch_loader=loader, now_fn=lambda: _DEC, audit_store=_AUDIT_STORE)


_BASE = ["--bankroll", "100"]


# ── Codes de sortie (PRD §18.3) ───────────────────────────────────────────────
def test_exit_0_recommended(capsys):
    code = _run(_BASE + ["--risk", "balanced", "--maturity", "supported-only"],
               _loader(_adapted(maturity="SUPPORTED")))
    out = capsys.readouterr().out
    assert code == 0
    assert "outcome: RECOMMENDED" in out and "BET" in out


def test_exit_0_review_candidates():
    code = _run(_BASE + ["--maturity", "include-experimental"],
               _loader(_adapted(maturity="EXPERIMENTAL")))
    assert code == 0                                          # revue produite = 0


def test_exit_2_no_evaluable_events():
    assert _run(_BASE, _loader()) == 2                        # batch vide


def test_exit_3_no_opportunity():
    code = _run(_BASE + ["--maturity", "supported-only"],
               _loader(_adapted(maturity="EXPERIMENTAL")))    # -> REJECTED
    assert code == 3


def test_exit_4_invalid_request(capsys):
    assert _run(["--bankroll", "0"], _loader(_adapted())) == 4   # bankroll > 0 requis
    assert "demande invalide" in capsys.readouterr().err


def test_exit_1_global_failure(capsys):
    def boom(decision_time):
        raise RuntimeError("scan cassé")
    assert cli.main(_BASE, batch_loader=boom, now_fn=lambda: _DEC) == 1
    assert "échec global" in capsys.readouterr().err


# ── Formats ───────────────────────────────────────────────────────────────────
def test_json_format_is_valid_json(capsys):
    code = _run(_BASE + ["--maturity", "supported-only", "--format", "json"],
               _loader(_adapted(maturity="SUPPORTED")))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["outcome"] == "RECOMMENDED"
    assert payload["portfolios"][0]["total_stake"]           # Decimal sérialisé en chaîne


def test_human_snapshot_recommended(capsys):
    _run(_BASE + ["--maturity", "supported-only"], _loader(_adapted(maturity="SUPPORTED")))
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("outcome: RECOMMENDED | audit: audit:")
    assert "BET home @ 2.10" in lines[1] and "stake" in lines[1]


# ── Arguments : target odds, filtres ──────────────────────────────────────────
def test_target_odds_parsed():
    code = _run(_BASE + ["--target-odds-min", "2.00", "--target-odds-max", "3.00",
                         "--maturity", "supported-only"], _loader(_adapted(maturity="SUPPORTED")))
    assert code == 0                                          # cote cible acceptée (soft)


def test_target_odds_require_both(capsys):
    assert _run(_BASE + ["--target-odds-min", "2.00"], _loader(_adapted())) == 4
    assert "ensemble" in capsys.readouterr().err


def test_sport_filter_excludes(capsys):
    # Candidat football + filtre tennis -> filtré -> aucune opportunité (code 3).
    code = _run(_BASE + ["--sports", "tennis", "--maturity", "supported-only"],
               _loader(_adapted(maturity="SUPPORTED", sport="football")))
    assert code == 3
    assert "USER_FILTERED_SPORT" in capsys.readouterr().out


# ── Smoke : le VRAI entrypoint câble axon -> recommend -> CLI Advisor ──────────
def test_axon_recommend_entrypoint_is_wired():
    """Preuve de bout en bout via `python -m src.ui.main recommend` (ce que lance
    le binaire `axon`), PAS un appel direct à main(). Empêche la disparition du
    branchement dans l'entrypoint."""
    result = subprocess.run(
        [sys.executable, "-m", "src.ui.main", "recommend", "--help"],
        cwd=_REPO, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0
    assert "axon recommend" in result.stdout and "--bankroll" in result.stdout
