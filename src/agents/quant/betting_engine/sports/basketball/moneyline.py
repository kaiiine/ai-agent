"""Basket NBA — modèle MONEYLINE (2-way) par Elo séquentiel + walk-forward point-in-time.

MÉTHODOLOGIE (V1, documentée — pas « une formule connue appliquée à l'aveugle ») :
- Cible probabiliste : P(victoire domicile) sur un match NBA (issue binaire, pas de nul).
- Modèle : Elo séquentiel. Choisi car (a) SANS FUITE PAR CONSTRUCTION — la note d'une
  équipe ne dépend que de ses matchs STRICTEMENT antérieurs ; (b) minimal et explicable ;
  (c) adapté à une issue binaire équipe-vs-équipe (contrairement à Dixon-Coles, propre au
  score de buts football — jamais réutilisé ici).
- Paramètres FIXES (jamais ajustés sur l'échantillon d'évaluation, comme le replay
  football) : `INIT_RATING=1500`, `K_FACTOR=20`, `HOME_EDGE=100` (≈ avantage domicile NBA
  connu ~0.60, PRIOR fixe, non fité), `MIN_PRIOR_GAMES=10` (démarrage à froid exclu, jamais
  de probabilité fabriquée sur des notes instables).
- Validation : walk-forward chronologique (prédire depuis les seules notes antérieures,
  PUIS mettre à jour). Baseline point-in-time = taux de victoire domicile des matchs
  strictement antérieurs. Métriques 2-way (Brier, ECE) hors échantillon.
- Maturité : verdict MÉCANIQUE via le framework générique (`evaluate_maturity`), avec des
  OBSERVATIONS propres au basket. Reste EXPERIMENTAL tant que les critères requis ne passent
  pas (CLV/freshness non mesurées ici -> bloquants). AUCUN faux SUPPORTED.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.agents.quant.betting_engine.calibration.experiment_registry import dataset_fingerprint
from src.agents.quant.betting_engine.clv import clv_readiness
from src.agents.quant.betting_engine.live_coverage import live_freshness_capability
from src.agents.quant.betting_engine.sports.pairwise_elo import (
    EloParams,
    PairwiseGame,
    run_pairwise_elo,
)
from src.agents.quant.betting_engine.maturity import (
    FRESHNESS_MEASURABLE,
    MaturityObservations,
    ModelSupportDecision,
    evaluate_maturity,
    load_maturity_policy,
)

MODEL_NAME = "basketball_moneyline"
MODEL_VERSION = "elo.v0"
NBA_LEAGUE_ID = "competition:basketball:usa:nba"
NBA_SEASON = "2022-2023"

# Paramètres de MÉTHODE (fixes, documentés) — jamais fités sur l'échantillon d'éval.
INIT_RATING = 1500.0
K_FACTOR = 20.0
HOME_EDGE = 100.0            # prior d'avantage domicile (≈ 0.60), non fité
MIN_PRIOR_GAMES = 10         # démarrage à froid : sous ce seuil, aucune prédiction

_CLASSES = ("home", "away")
_FIXTURE = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "nba_api_sports_games.json"


@dataclass(frozen=True)
class BasketballGame:
    game_id: str
    tipoff: datetime
    home_team_id: str
    away_team_id: str
    home_points: int
    away_points: int

    @property
    def outcome(self) -> str:
        # NBA : pas de nul (prolongations jusqu'à décision).
        return "home" if self.home_points > self.away_points else "away"


def load_nba_games(path: Path = _FIXTURE) -> tuple[list[BasketballGame], str]:
    """Charge le dataset RÉEL (api-sports basketball) -> `(games, dataset_fingerprint)`."""
    raw = path.read_bytes()
    data = json.loads(raw)
    games = [
        BasketballGame(
            game_id=str(g["id"]),
            tipoff=datetime.fromisoformat(g["date"].replace("Z", "+00:00")),
            home_team_id=str(g["home_id"]), away_team_id=str(g["away_id"]),
            home_points=int(g["home_pts"]), away_points=int(g["away_pts"]),
        )
        for g in data["games"]
    ]
    return games, dataset_fingerprint(raw)


def _p_home(rating_home: float, rating_away: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(rating_home - rating_away + HOME_EDGE) / 400.0))


def elo_ratings_as_of(games: list[BasketballGame], cutoff: datetime):
    """Notes Elo + nombre de matchs joués par équipe, à partir des SEULS matchs
    STRICTEMENT antérieurs à `cutoff` — sans fuite par construction. Réutilisé par le
    walk-forward ET l'évaluation live point-in-time (une seule implémentation Elo)."""
    ratings: dict[str, float] = {}
    played: Counter = Counter()
    for g in sorted((x for x in games if x.tipoff < cutoff), key=lambda x: x.tipoff):
        rh = ratings.get(g.home_team_id, INIT_RATING)
        ra = ratings.get(g.away_team_id, INIT_RATING)
        ph = _p_home(rh, ra)
        y = 1.0 if g.outcome == "home" else 0.0
        ratings[g.home_team_id] = rh + K_FACTOR * (y - ph)
        ratings[g.away_team_id] = ra + K_FACTOR * ((1.0 - y) - (1.0 - ph))
        played[g.home_team_id] += 1
        played[g.away_team_id] += 1
    return ratings, played


def _brier2(prob: dict[str, float], outcome: str) -> float:
    return sum((prob[c] - (1.0 if c == outcome else 0.0)) ** 2 for c in _CLASSES)


def _binary_ece(pairs: list[tuple[float, float]], n_bins: int = 10) -> float | None:
    """ECE binaire (classe « home ») : |confiance moyenne − fréquence réelle| pondéré."""
    if not pairs:
        return None
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    n = len(pairs)
    ece = 0.0
    for b in bins:
        if not b:
            continue
        conf = sum(p for p, _ in b) / len(b)
        acc = sum(y for _, y in b) / len(b)
        ece += (len(b) / n) * abs(conf - acc)
    return round(ece, 6)


@dataclass(frozen=True)
class EloWalkForward:
    model_predictions: list[tuple[dict, str]]
    baseline_predictions: list[tuple[dict, str]]
    predicted_game_ids: tuple[str, ...]            # aligné avec model_predictions (anti-fuite testable)
    fold_months: tuple[str, ...]
    n_total: int
    n_evaluated: int
    exclusions: dict
    raw_predictions: list = field(default_factory=list)
    n_calibrated: int = 0


#: Paramètres NBA au format du harness pairwise. Ce sont les MÊMES valeurs que
#: les constantes historiques du module — elles ne sont pas re-choisies ici,
#: seulement redites dans le vocabulaire commun.
NBA_PARAMS = EloParams(
    init_rating=INIT_RATING, k_factor=K_FACTOR, home_edge=HOME_EDGE,
    min_prior_games=MIN_PRIOR_GAMES,
    notes="NBA moneyline — paramètres fixes, non fités sur l'évaluation")

#: La calibration NBA est ACTIVÉE, et elle seule. Benchmark point-in-time sur
#: 3 587 prédictions hors échantillon :
#:
#:                Brier      logloss      ECE
#:     brut      0.22412     0.63939    0.07089   (échec du critère à 0,05)
#:     histo     0.22068     0.63148    0.02547   (les TROIS métriques s'améliorent)
#:
#: Platt fait aussi bien pour 400× le coût ; l'isotonique dégrade tout. Le volley
#: a subi le même benchmark et l'a REFUSÉ — son logloss s'y dégradait. Aucun
#: calibrateur ne s'active par famille : chacun se mérite sur ses propres
#: mesures.
CALIBRATION_ACTIVE = True


def run_elo_walk_forward(games: list[BasketballGame]) -> EloWalkForward:
    """Rejeu chronologique SANS FUITE, délégué au harness pairwise COMMUN.

    Cette fonction portait sa propre copie de la boucle — mêmes notes Elo, même
    exclusion du démarrage à froid, même baseline point-in-time — à ceci près
    qu'elle lisait des constantes de module au lieu d'un `EloParams`. Deux
    moteurs pour un seul comportement, dont un seul recevait la calibration.

    Elle devient une conversion de vocabulaire : `BasketballGame` -> `PairwiseGame`,
    constantes -> `EloParams`. Le rejeu, l'anti-fuite, les folds et la baseline
    viennent tous du harness unique.
    """
    convertis = [
        PairwiseGame(game_id=g.game_id, tipoff=g.tipoff,
                     home_id=g.home_team_id, away_id=g.away_team_id,
                     home_score=g.home_points, away_score=g.away_points)
        for g in games
    ]
    run = run_pairwise_elo(convertis, NBA_PARAMS, calibrate=CALIBRATION_ACTIVE)
    return EloWalkForward(
        model_predictions=run.model_predictions,
        baseline_predictions=run.baseline_predictions,
        predicted_game_ids=run.predicted_game_ids,
        fold_months=run.fold_months,
        n_total=run.n_total, n_evaluated=run.n_evaluated,
        exclusions=run.exclusions,
        raw_predictions=run.raw_predictions,
        n_calibrated=run.n_calibrated)


def _run_elo_walk_forward_historique(games: list[BasketballGame]) -> EloWalkForward:
    """Ancienne boucle, conservée le temps de prouver l'équivalence."""
    ordered = sorted(games, key=lambda g: g.tipoff)
    ratings: dict[str, float] = {}
    played: Counter = Counter()
    prior_outcomes: list[str] = []

    model_preds: list[tuple[dict, str]] = []
    baseline_preds: list[tuple[dict, str]] = []
    predicted_ids: list[str] = []
    fold_months: list[str] = []
    exclusions: Counter = Counter()

    for g in ordered:
        rh = ratings.get(g.home_team_id, INIT_RATING)
        ra = ratings.get(g.away_team_id, INIT_RATING)
        eligible = played[g.home_team_id] >= MIN_PRIOR_GAMES and played[g.away_team_id] >= MIN_PRIOR_GAMES

        if eligible:
            ph = _p_home(rh, ra)
            model_preds.append(({"home": ph, "away": 1.0 - ph}, g.outcome))
            predicted_ids.append(g.game_id)
            fold_months.append(g.tipoff.isoformat()[:7])
            # Baseline point-in-time : taux de victoire domicile des matchs antérieurs.
            if prior_outcomes:
                hr = prior_outcomes.count("home") / len(prior_outcomes)
                baseline_preds.append(({"home": hr, "away": 1.0 - hr}, g.outcome))
        else:
            exclusions["cold_start_insufficient_prior_games"] += 1

        # Mise à jour Elo (après la prédiction — jamais avant : pas de fuite).
        ph_actual = _p_home(rh, ra)
        y = 1.0 if g.outcome == "home" else 0.0
        ratings[g.home_team_id] = rh + K_FACTOR * (y - ph_actual)
        ratings[g.away_team_id] = ra + K_FACTOR * ((1.0 - y) - (1.0 - ph_actual))
        played[g.home_team_id] += 1
        played[g.away_team_id] += 1
        prior_outcomes.append(g.outcome)

    return EloWalkForward(
        model_predictions=model_preds, baseline_predictions=baseline_preds,
        predicted_game_ids=tuple(predicted_ids), fold_months=tuple(fold_months),
        n_total=len(ordered), n_evaluated=len(model_preds), exclusions=dict(exclusions))


@dataclass(frozen=True)
class BasketballAssessment:
    decision: ModelSupportDecision
    observations: MaturityObservations
    run: EloWalkForward
    metrics: dict


def assess_nba(path: Path = _FIXTURE, *, odds_observations=(),
               live_freshness_status: str | None = None) -> BasketballAssessment:
    """Verdict de maturité MÉCANIQUE du modèle NBA moneyline (walk-forward réel).
    EXPERIMENTAL tant que les critères requis ne passent pas — jamais un faux SUPPORTED."""
    # Mesurée, non déclarée : le défaut valait `FRESHNESS_MEASURABLE` alors que la
    # Gateway ne sert aucune donnée de basket. Le paramètre reste injectable pour
    # les tests, mais son absence appelle désormais la mesure.
    if live_freshness_status is None:
        live_freshness_status = live_freshness_capability(NBA_LEAGUE_ID)
    policy = load_maturity_policy()
    games, _fp = load_nba_games(path)
    run = run_elo_walk_forward(games)

    model_brier = sum(_brier2(p, o) for p, o in run.model_predictions) / run.n_evaluated
    # Baselines 2-way : uniforme (0.5/0.5) et taux domicile point-in-time.
    uniform_brier = sum(_brier2({"home": 0.5, "away": 0.5}, o) for _, o in run.model_predictions) / run.n_evaluated
    base_brier = (sum(_brier2(p, o) for p, o in run.baseline_predictions) / len(run.baseline_predictions)
                  if run.baseline_predictions else uniform_brier)
    best_baseline = min(uniform_brier, base_brier)
    ece = _binary_ece([(p["home"], 1.0 if o == "home" else 0.0) for p, o in run.model_predictions])

    # Spread de Brier par fold mensuel (stabilité temporelle).
    by_month: dict[str, list[float]] = {}
    for (p, o), m in zip(run.model_predictions, run.fold_months):
        by_month.setdefault(m, []).append(_brier2(p, o))
    month_briers = [sum(v) / len(v) for v in by_month.values()]
    fold_spread = (max(month_briers) - min(month_briers)) if len(month_briers) >= 2 else None

    readiness = clv_readiness(list(odds_observations),
                              confidence=policy.criteria["clv_confidence_level"])

    observations = MaturityObservations(
        n_evaluated=run.n_evaluated,
        n_temporal_folds=len(by_month),
        calibration_error=ece,
        model_brier=round(model_brier, 6),
        best_baseline_brier=round(best_baseline, 6),
        data_coverage=round(run.n_evaluated / run.n_total, 4) if run.n_total else None,
        mean_data_quality=1.0,                         # scores complets et vérifiés (api-sports)
        fold_brier_spread=round(fold_spread, 4) if fold_spread is not None else None,
        clv_status=readiness.status,
        clv_mean=readiness.mean_clv,
        clv_n_events=readiness.n_events,
        clv_lower_bound=readiness.clv_lower_bound,
        # Freshness déclarée par l'appelant : NON mesurable tant que le live n'est pas câblé.
        live_freshness_status=live_freshness_status,
    )
    decision = evaluate_maturity(
        model_name=MODEL_NAME, model_version=MODEL_VERSION,
        observations=observations, policy=policy)
    metrics = {"model_brier": model_brier, "uniform_brier": uniform_brier,
               "home_rate_baseline_brier": base_brier, "ece": ece,
               "beats_baseline": model_brier < best_baseline}
    return BasketballAssessment(decision=decision, observations=observations, run=run, metrics=metrics)
