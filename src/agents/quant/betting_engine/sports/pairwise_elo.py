"""Harness Elo pairwise GÉNÉRIQUE (wave finale §6) — réutilisable, params PAR SPORT.

Une SEULE implémentation Elo (séquentielle, sans fuite par construction) + walk-forward
2-way + métriques binaires + verdict de maturité mécanique. Chaque sport fournit ses
DONNÉES et ses PARAMÈTRES (jamais copiés à l'aveugle : K/home_edge/cold-start documentés
et justifiés par sport). Le harness ne décide JAMAIS qu'un modèle est bon : il MESURE
(bat-il la baseline hors échantillon ?) et laisse le verdict de maturité au framework.

Ne suppose pas `home/draw/away` : issue binaire home/away (pas de nul — le caller filtre
les nuls éventuels). `evaluate_maturity` reste la source unique du statut (EXPERIMENTAL
tant que les critères ne passent pas).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from src.agents.quant.betting_engine.clv import clv_readiness
from src.agents.quant.betting_engine.maturity import (
    FRESHNESS_NOT_MEASURABLE,
    MaturityObservations,
    ModelSupportDecision,
    evaluate_maturity,
    load_maturity_policy,
)

_CLASSES = ("home", "away")


@dataclass(frozen=True)
class EloParams:
    """Paramètres Elo PROPRES à un sport (fixes, documentés — jamais fités sur l'éval)."""
    init_rating: float
    k_factor: float
    home_edge: float                  # prior d'avantage domicile (0 si terrain neutre)
    min_prior_games: int              # démarrage à froid : aucune prédiction en-dessous
    notes: str = ""


@dataclass(frozen=True)
class PairwiseGame:
    game_id: str
    tipoff: datetime
    home_id: str
    away_id: str
    home_score: int
    away_score: int

    @property
    def outcome(self) -> str:
        return "home" if self.home_score > self.away_score else "away"


def p_home(rating_home: float, rating_away: float, params: EloParams) -> float:
    return 1.0 / (1.0 + 10 ** (-(rating_home - rating_away + params.home_edge) / 400.0))


def elo_ratings_as_of(games: list[PairwiseGame], cutoff: datetime, params: EloParams):
    """Notes Elo + matchs joués par équipe, à partir des SEULS matchs < cutoff (sans fuite)."""
    ratings: dict[str, float] = {}
    played: Counter = Counter()
    for g in sorted((x for x in games if x.tipoff < cutoff), key=lambda x: x.tipoff):
        rh = ratings.get(g.home_id, params.init_rating)
        ra = ratings.get(g.away_id, params.init_rating)
        ph = p_home(rh, ra, params)
        y = 1.0 if g.outcome == "home" else 0.0
        ratings[g.home_id] = rh + params.k_factor * (y - ph)
        ratings[g.away_id] = ra + params.k_factor * ((1.0 - y) - (1.0 - ph))
        played[g.home_id] += 1
        played[g.away_id] += 1
    return ratings, played


def _brier2(prob: dict[str, float], outcome: str) -> float:
    return sum((prob[c] - (1.0 if c == outcome else 0.0)) ** 2 for c in _CLASSES)


def _binary_ece(pairs: list[tuple[float, float]], n_bins: int = 10) -> float | None:
    if not pairs:
        return None
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        bins[min(int(p * n_bins), n_bins - 1)].append((p, y))
    n = len(pairs)
    return round(sum((len(b) / n) * abs(sum(p for p, _ in b) / len(b) - sum(y for _, y in b) / len(b))
                     for b in bins if b), 6)


@dataclass(frozen=True)
class PairwiseEloRun:
    model_predictions: list[tuple[dict, str]]
    baseline_predictions: list[tuple[dict, str]]
    predicted_game_ids: tuple[str, ...]
    fold_months: tuple[str, ...]
    n_total: int
    n_evaluated: int
    exclusions: dict = field(default_factory=dict)


def run_pairwise_elo(games: list[PairwiseGame], params: EloParams) -> PairwiseEloRun:
    """Rejeu chronologique SANS FUITE : prédire depuis les notes antérieures, puis mettre
    à jour. Démarrage à froid exclu (aucune probabilité fabriquée)."""
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
        if played[g.home_id] >= params.min_prior_games and played[g.away_id] >= params.min_prior_games:
            ph = p_home(rh, ra, params)
            model_preds.append(({"home": ph, "away": 1.0 - ph}, g.outcome))
            ids.append(g.game_id)
            months.append(g.tipoff.isoformat()[:7])
            if prior:
                hr = prior.count("home") / len(prior)
                baseline_preds.append(({"home": hr, "away": 1.0 - hr}, g.outcome))
        else:
            exclusions["cold_start_insufficient_prior_games"] += 1
        pa = p_home(rh, ra, params)
        y = 1.0 if g.outcome == "home" else 0.0
        ratings[g.home_id] = rh + params.k_factor * (y - pa)
        ratings[g.away_id] = ra + params.k_factor * ((1.0 - y) - (1.0 - pa))
        played[g.home_id] += 1
        played[g.away_id] += 1
        prior.append(g.outcome)

    return PairwiseEloRun(model_preds, baseline_preds, tuple(ids), tuple(months),
                          len(ordered), len(model_preds), dict(exclusions))


@dataclass(frozen=True)
class PairwiseAssessment:
    decision: ModelSupportDecision
    observations: MaturityObservations
    run: PairwiseEloRun
    metrics: dict


def assess_pairwise_elo(
    games: list[PairwiseGame], params: EloParams, model_name: str, model_version: str,
    *, odds_observations=(), live_freshness_status: str = FRESHNESS_NOT_MEASURABLE,
) -> PairwiseAssessment:
    """Verdict de maturité MÉCANIQUE. EXPERIMENTAL tant que les critères ne passent pas.
    `beats_baseline` est MESURÉ hors échantillon — jamais présumé. `odds_observations`
    (vide par défaut) alimente la CLV réelle ; `live_freshness_status` est déclaré par
    le sport quand son chemin live est câblé (sinon NOT_MEASURABLE)."""
    policy = load_maturity_policy()
    run = run_pairwise_elo(games, params)
    n = run.n_evaluated
    model_brier = sum(_brier2(p, o) for p, o in run.model_predictions) / n
    uniform_brier = sum(_brier2({"home": 0.5, "away": 0.5}, o) for _, o in run.model_predictions) / n
    base_brier = (sum(_brier2(p, o) for p, o in run.baseline_predictions) / len(run.baseline_predictions)
                  if run.baseline_predictions else uniform_brier)
    best_baseline = min(uniform_brier, base_brier)
    ece = _binary_ece([(p["home"], 1.0 if o == "home" else 0.0) for p, o in run.model_predictions])

    by_month: dict[str, list[float]] = {}
    for (p, o), m in zip(run.model_predictions, run.fold_months):
        by_month.setdefault(m, []).append(_brier2(p, o))
    month_briers = [sum(v) / len(v) for v in by_month.values()]
    fold_spread = (max(month_briers) - min(month_briers)) if len(month_briers) >= 2 else None
    readiness = clv_readiness(list(odds_observations),
                              confidence=policy.criteria["clv_confidence_level"])

    observations = MaturityObservations(
        n_evaluated=n, n_temporal_folds=len(by_month), calibration_error=ece,
        model_brier=round(model_brier, 6), best_baseline_brier=round(best_baseline, 6),
        data_coverage=round(n / run.n_total, 4) if run.n_total else None,
        mean_data_quality=1.0, fold_brier_spread=round(fold_spread, 4) if fold_spread is not None else None,
        clv_status=readiness.status, clv_mean=readiness.mean_clv,
        clv_n_events=readiness.n_events, clv_lower_bound=readiness.clv_lower_bound,
        live_freshness_status=live_freshness_status)
    decision = evaluate_maturity(model_name=model_name, model_version=model_version,
                                 observations=observations, policy=policy)
    metrics = {"model_brier": model_brier, "uniform_brier": uniform_brier,
               "home_rate_baseline_brier": base_brier, "ece": ece,
               "beats_baseline": model_brier < best_baseline}
    return PairwiseAssessment(decision, observations, run, metrics)
