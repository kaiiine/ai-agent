"""CLI `axon recommend` — adaptateur MINCE (PRD §18). Aucune logique métier : il
parse les arguments, construit une `RecommendationRequest`, délègue au pipeline
pur, et rend le résultat (human/json). Framework-free (argparse uniquement).

Codes de sortie (PRD §18.3) :
  0 = recommandation OU candidats de revue produits
  1 = échec global (scan/technique)
  2 = scan réussi mais aucun événement évaluable
  3 = événements évalués mais aucune opportunité
  4 = demande invalide
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from .domain.enums import MaturityPolicy, RecommendationOutcome, RiskProfile
from .domain.recommendations import RecommendationResponse
from .domain.requests import OddsRange, RecommendationRequest
from .domain import serialization
from .input_adapter.schema import AdaptedBatch
from .combos import load_combo_policy
from .pipeline import run_pipeline
from .policy import load_policy_config
from .portfolio import load_portfolio_caps
from .ranking import load_ranking_profiles
from .recommendation import load_sizing_profiles

_RISK = {"conservative": RiskProfile.CONSERVATIVE, "balanced": RiskProfile.BALANCED,
         "aggressive": RiskProfile.AGGRESSIVE}
_MATURITY = {"supported-only": MaturityPolicy.SUPPORTED_ONLY,
             "include-experimental": MaturityPolicy.INCLUDE_EXPERIMENTAL_FOR_REVIEW}
_EXIT = {RecommendationOutcome.RECOMMENDED: 0, RecommendationOutcome.REVIEW_CANDIDATES: 0,
         RecommendationOutcome.NO_EVALUABLE_EVENTS: 2, RecommendationOutcome.NO_OPPORTUNITY: 3}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="axon recommend", description="Recommandation de paris (Advisor).")
    p.add_argument("--bankroll", required=True)
    p.add_argument("--currency", default="EUR")
    p.add_argument("--target-odds-min")
    p.add_argument("--target-odds-max")
    p.add_argument("--max-total-stake")
    p.add_argument("--risk", choices=tuple(_RISK), default="balanced")
    p.add_argument("--maturity", choices=tuple(_MATURITY), default="supported-only")
    p.add_argument("--ranking-profile", default="balanced_v1")
    p.add_argument("--max-selections", type=int, default=1)
    p.add_argument("--max-portfolios", type=int, default=1)
    p.add_argument("--allow-combos", action="store_true")
    p.add_argument("--max-combo-legs", type=int, default=2)
    p.add_argument("--sports", nargs="*")
    p.add_argument("--competitions", nargs="*")
    p.add_argument("--bookmakers", nargs="*")
    p.add_argument("--market-types", nargs="*")
    # request_id FRAIS par invocation (unicité requise par l'audit/idempotence,
    # Lot 10 §0). Un --request-id explicite n'est fourni que pour un rejeu ciblé.
    p.add_argument("--request-id", default=None)
    p.add_argument("--format", choices=("human", "json"), default="human")
    return p


def _fset(values):
    return None if values is None else frozenset(values)


def _build_request(args, decision_time: datetime) -> RecommendationRequest:
    """Peut lever ValueError/TypeError -> demande invalide (code 4)."""
    odds_min, odds_max = args.target_odds_min, args.target_odds_max
    if (odds_min is None) != (odds_max is None):
        raise ValueError("--target-odds-min et --target-odds-max doivent être fournis ensemble")
    target = None if odds_min is None else OddsRange(Decimal(odds_min), Decimal(odds_max))
    request_id = args.request_id or f"req:{uuid.uuid4().hex}"   # frais si non fourni (§0)
    return RecommendationRequest(
        request_id=request_id, decision_time=decision_time, bankroll=Decimal(args.bankroll),
        currency=args.currency, allowed_sports=_fset(args.sports),
        allowed_competitions=_fset(args.competitions), allowed_bookmakers=_fset(args.bookmakers),
        allowed_market_types=_fset(args.market_types), target_total_odds=target,
        max_total_stake=None if args.max_total_stake is None else Decimal(args.max_total_stake),
        max_selections=args.max_selections, max_portfolios=args.max_portfolios,
        allow_singles=True, allow_combos=args.allow_combos, max_combo_legs=args.max_combo_legs,
        risk_profile=_RISK[args.risk], maturity_policy=_MATURITY[args.maturity],
        ranking_profile=args.ranking_profile, excluded_event_ids=frozenset(),
        excluded_participant_ids=frozenset(), excluded_market_types=frozenset())


# ── Rendu (pur) ───────────────────────────────────────────────────────────────
def render_human(response: RecommendationResponse) -> list[str]:
    lines = [f"outcome: {response.outcome.value} | audit: {response.audit_id}"]
    for pf in response.portfolios:
        line = pf.lines[0]
        lines.append(
            f"  BET {line.legs[0].selection} @ {line.total_odds} | stake {pf.total_stake} "
            f"{response.request_id} | EV {line.expected_value} (low {line.worst_case_ev}) "
            f"| unallocated {pf.unallocated_bankroll}")
    if response.review_candidates:
        lines.append(f"  review: {len(response.review_candidates)} candidat(s) à examiner")
    if response.rejection_summary:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(response.rejection_summary.items()))
        lines.append(f"  rejected: {summary}")
    return lines


def _load_configs() -> dict:
    return {
        "policy_config": load_policy_config(),
        "ranking_profiles": load_ranking_profiles(),
        "sizing_profiles": load_sizing_profiles(),
        "portfolio_caps": load_portfolio_caps(),
        "combo_policy": load_combo_policy(),
    }


def _default_batch_loader(decision_time: datetime) -> AdaptedBatch:  # pragma: no cover (I/O réelle)
    # Imports lazy : `axon recommend --help` ne charge pas la chaîne Betting Engine.
    from .input_adapter.betting_engine_adapter import load_and_adapt
    from ..betting_engine.bookmakers.winamax.connector import WinamaxConnector
    from ..betting_engine.bookmakers.winamax.catalogue import all_events
    from ..betting_engine.bookmakers.bookmaker_registry import BookmakerEventResolver
    from ..gateway.core.identity_resolver import IdentityResolver
    from ..gateway.core.identity_data import TEAMS
    from ..gateway import gateway as sports_gateway
    resolver = BookmakerEventResolver(IdentityResolver(TEAMS))
    # DÉCOUVERTE complète (toutes compétitions) : les non-supportés sont ISOLÉS
    # (SkippedEvaluation avec raison typée), jamais écartés au scan ni arrêtant le run.
    return load_and_adapt(WinamaxConnector(), sports_gateway=sports_gateway,
                          event_resolver=resolver, catalogue=all_events,
                          now_fn=lambda: decision_time)


def _default_audit_store():
    from .audit import JsonlAuditStore, load_audit_config
    cfg = load_audit_config()
    repo_root = pathlib.Path(__file__).resolve().parents[5]
    return JsonlAuditStore(repo_root / cfg.audit_store_path)


def _persist_audit(request, batch, result, cfg, audit_store) -> None:
    from .audit import build_config_snapshots, build_envelope
    snapshots = build_config_snapshots(allow_combos=request.allow_combos)
    envelope = build_envelope(request, batch, snapshots, result.trace, result.recommendation)
    (audit_store or _default_audit_store()).append(envelope)


def main(argv: list[str] | None = None, *, batch_loader: Callable[[datetime], AdaptedBatch] | None = None,
         now_fn: Callable[[], datetime] = _utcnow, configs: dict | None = None, audit_store=None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        request = _build_request(args, now_fn())
    except (ValueError, TypeError, InvalidOperation) as exc:
        print(f"demande invalide : {exc}", file=sys.stderr)
        return 4

    loader = batch_loader or _default_batch_loader
    cfg = configs or _load_configs()
    try:
        batch = loader(request.decision_time)
        result = run_pipeline(batch, request, **cfg)
        _persist_audit(request, batch, result, cfg, audit_store)
    except Exception as exc:   # noqa: BLE001 — scan/technique -> code 1
        print(f"échec global : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    response = result.recommendation
    if args.format == "json":
        print(serialization.to_json(response))
    else:
        for line in render_human(response):
            print(line)

    return _EXIT[response.outcome]


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
