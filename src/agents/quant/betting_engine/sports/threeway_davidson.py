"""Harness Elo 3-WAY (Davidson) GÉNÉRIQUE (wave 3 §3) — pour marchés à résultat
RÉGLEMENTAIRE 3 issues (home/draw/away), ex. hockey NHL, rugby.

Méthodologie : Elo séquentiel (issue réglementaire, draw=0.5) + **modèle de Davidson
(1970)** — l'extension CANONIQUE de Bradley-Terry/Elo aux nuls, PAS Dixon-Coles (propre
au score de buts football, jamais réutilisé). Sans fuite par construction (notes issues
des seuls matchs antérieurs) ; `nu` (propension au nul) estimé POINT-IN-TIME depuis le
taux de nul des matchs antérieurs. Verdict de maturité mécanique via le framework générique.

Davidson : R = 10^(rating/400) ; P(home)=Rh/(Rh+Ra+ν√(RhRa)), P(draw)=ν√(RhRa)/(…),
P(away)=Ra/(…). ν=0 -> Bradley-Terry 2-way ; ν>0 -> masse sur le nul.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from src.agents.quant.betting_engine.clv import clv_readiness
from src.agents.quant.betting_engine.maturity import (
    FRESHNESS_MEASURABLE,
    FRESHNESS_NOT_MEASURABLE,
    MaturityObservations,
    ModelSupportDecision,
    evaluate_maturity,
    load_maturity_policy,
)

_CLASSES = ("home", "draw", "away")


@dataclass(frozen=True)
class Davidson3Params:
    init_rating: float
    k_factor: float
    home_edge: float           # dérivé du taux domicile RÉGLEMENTAIRE décisif
    min_prior_games: int
    default_draw_rate: float   # amorçage de nu avant historique suffisant
    notes: str = ""


@dataclass(frozen=True)
class ThreeWayGame:
    game_id: str
    tipoff: datetime
    home_id: str
    away_id: str
    outcome: str               # "home" | "draw" | "away" (RÉGLEMENTAIRE)


def _nu(draw_rate: float) -> float:
    # A notes égales, P(draw) = nu/(2+nu) -> nu = 2·dr/(1-dr). Borne basse pour stabilité.
    return max(0.05, 2.0 * draw_rate / (1.0 - draw_rate)) if draw_rate < 0.999 else 50.0


def davidson_probs(rh: float, ra: float, home_edge: float, nu: float) -> dict[str, float]:
    Rh = 10 ** ((rh + home_edge) / 400.0)
    Ra = 10 ** (ra / 400.0)
    d = nu * math.sqrt(Rh * Ra)
    tot = Rh + Ra + d
    return {"home": Rh / tot, "draw": d / tot, "away": Ra / tot}


def regulation_ratings_as_of(games: list[ThreeWayGame], cutoff: datetime, params: Davidson3Params):
    """Notes Elo, matchs joués et taux de nul, à partir des SEULS matchs réglementaires
    STRICTEMENT antérieurs à `cutoff` (sans fuite). Réutilisé par le walk-forward ET
    l'évaluation live point-in-time — une seule implémentation Elo+Davidson."""
    ratings: dict[str, float] = {}
    played: Counter = Counter()
    prior: list[str] = []
    for g in sorted((x for x in games if x.tipoff < cutoff), key=lambda x: x.tipoff):
        rh = ratings.get(g.home_id, params.init_rating)
        ra = ratings.get(g.away_id, params.init_rating)
        dr = (prior.count("draw") / len(prior)) if len(prior) >= 100 else params.default_draw_rate
        p = davidson_probs(rh, ra, params.home_edge, _nu(dr))
        exp = p["home"] + 0.5 * p["draw"]
        y = {"home": 1.0, "draw": 0.5, "away": 0.0}[g.outcome]
        ratings[g.home_id] = rh + params.k_factor * (y - exp)
        ratings[g.away_id] = ra + params.k_factor * ((1.0 - y) - (1.0 - exp))
        played[g.home_id] += 1
        played[g.away_id] += 1
        prior.append(g.outcome)
    draw_rate = (prior.count("draw") / len(prior)) if len(prior) >= 100 else params.default_draw_rate
    return ratings, played, draw_rate


def _brier3(prob: dict[str, float], outcome: str) -> float:
    return sum((prob[c] - (1.0 if c == outcome else 0.0)) ** 2 for c in _CLASSES)


def _logloss3(prob: dict[str, float], outcome: str) -> float:
    return -math.log(max(prob[outcome], 1e-9))


def _pooled_ece(preds: list[tuple[dict, str]], n_bins: int = 10) -> float | None:
    """ECE multiclasse mutualisée sur les 3 classes (même convention que le football)."""
    pairs = [(p[c], 1.0 if o == c else 0.0) for p, o in preds for c in _CLASSES]
    if not pairs:
        return None
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        bins[min(int(p * n_bins), n_bins - 1)].append((p, y))
    n = len(pairs)
    return round(sum((len(b) / n) * abs(sum(p for p, _ in b) / len(b) - sum(y for _, y in b) / len(b))
                     for b in bins if b), 6)


@dataclass(frozen=True)
class ThreeWayRun:
    model_predictions: list[tuple[dict, str]]
    baseline_predictions: list[tuple[dict, str]]
    predicted_game_ids: tuple[str, ...]
    fold_months: tuple[str, ...]
    n_total: int
    n_evaluated: int
    exclusions: dict = field(default_factory=dict)


def run_threeway_elo(games: list[ThreeWayGame], params: Davidson3Params) -> ThreeWayRun:
    ordered = sorted(games, key=lambda g: g.tipoff)
    ratings: dict[str, float] = {}
    played: Counter = Counter()
    prior: list[str] = []
    model_preds: list[tuple[dict, str]] = []
    baseline_preds: list[tuple[dict, str]] = []
    ids: list[str] = []
    months: list[str] = []
    exclusions: Counter = Counter()

    for g in ordered:
        rh = ratings.get(g.home_id, params.init_rating)
        ra = ratings.get(g.away_id, params.init_rating)
        dr = (prior.count("draw") / len(prior)) if len(prior) >= 100 else params.default_draw_rate
        nu = _nu(dr)
        if played[g.home_id] >= params.min_prior_games and played[g.away_id] >= params.min_prior_games:
            model_preds.append((davidson_probs(rh, ra, params.home_edge, nu), g.outcome))
            ids.append(g.game_id)
            months.append(g.tipoff.isoformat()[:7])
            if prior:
                cnt = Counter(prior)
                base = {c: cnt.get(c, 0) / len(prior) for c in _CLASSES}   # base-rate point-in-time
                baseline_preds.append((base, g.outcome))
        else:
            exclusions["cold_start_insufficient_prior_games"] += 1
        # Mise à jour Elo (issue réglementaire) : score attendu = P(home)+0.5·P(draw).
        p = davidson_probs(rh, ra, params.home_edge, nu)
        exp = p["home"] + 0.5 * p["draw"]
        y = {"home": 1.0, "draw": 0.5, "away": 0.0}[g.outcome]
        ratings[g.home_id] = rh + params.k_factor * (y - exp)
        ratings[g.away_id] = ra + params.k_factor * ((1.0 - y) - (1.0 - exp))
        played[g.home_id] += 1
        played[g.away_id] += 1
        prior.append(g.outcome)

    return ThreeWayRun(model_preds, baseline_preds, tuple(ids), tuple(months),
                       len(ordered), len(model_preds), dict(exclusions))


@dataclass(frozen=True)
class ThreeWayAssessment:
    decision: ModelSupportDecision
    observations: MaturityObservations
    run: ThreeWayRun
    metrics: dict


def assess_threeway(
    games: list[ThreeWayGame], params: Davidson3Params, model_name: str, model_version: str,
    *, live_freshness_status: str = FRESHNESS_NOT_MEASURABLE,
) -> ThreeWayAssessment:
    run = run_threeway_elo(games, params)
    n = run.n_evaluated
    model_brier = sum(_brier3(p, o) for p, o in run.model_predictions) / n
    base_brier = (sum(_brier3(p, o) for p, o in run.baseline_predictions) / len(run.baseline_predictions)
                  if run.baseline_predictions else 2.0)
    ece = _pooled_ece(run.model_predictions)
    by_month: dict[str, list[float]] = {}
    for (p, o), m in zip(run.model_predictions, run.fold_months):
        by_month.setdefault(m, []).append(_brier3(p, o))
    month_briers = [sum(v) / len(v) for v in by_month.values()]
    fold_spread = (max(month_briers) - min(month_briers)) if len(month_briers) >= 2 else None
    readiness = clv_readiness([])

    observations = MaturityObservations(
        n_evaluated=n, n_temporal_folds=len(by_month), calibration_error=ece,
        model_brier=round(model_brier, 6), best_baseline_brier=round(base_brier, 6),
        data_coverage=round(n / run.n_total, 4) if run.n_total else None,
        mean_data_quality=1.0, fold_brier_spread=round(fold_spread, 4) if fold_spread is not None else None,
        clv_status=readiness.status, clv_mean=readiness.mean_clv,
        live_freshness_status=live_freshness_status)
    decision = evaluate_maturity(model_name=model_name, model_version=model_version,
                                 observations=observations, policy=load_maturity_policy())
    metrics = {"model_brier3": model_brier, "baseline_brier3": base_brier, "ece": ece,
               "model_logloss": sum(_logloss3(p, o) for p, o in run.model_predictions) / n,
               "beats_baseline": model_brier < base_brier}
    return ThreeWayAssessment(decision, observations, run, metrics)
