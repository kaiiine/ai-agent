"""Tennis — modèle Elo (ATP/WTA séparés), walk-forward sans fuite.

CHOIX MÉTHODOLOGIQUE — issu d'une COMPARAISON MESURÉE (`model_comparison.py`), pas d'une
supposition. Protocole : DEV (saisons ≤2021) pour choisir, HOLDOUT (≥2022) pour confirmer,
comparaisons de Brier APPARIÉES PAR MATCH avec IC bootstrap 95 %.

Résultat (holdout, ATP puis WTA) :
- elo vs `rank_logistic` : delta -0.0041 / -0.0077, IC EXCLUANT 0 -> Elo bat significativement
  la baseline classement (et a fortiori `rank_favorite` : -0.0135 / -0.0162) ;
- elo vs `elo_surface` et vs `glicko2` : IC CONTENANT 0 -> aucune supériorité démontrée des
  variantes plus complexes.
=> À skill statistiquement ÉQUIVALENT, on retient le modèle le PLUS SIMPLE et le MIEUX
CALIBRÉ : Elo classique. ECE holdout : elo 0.0247/0.0209 vs elo_surface 0.0286/0.0287 vs
glicko2 0.0302/0.0285. La calibration prime ici car la décision de pari consomme une
PROBABILITÉ (EV), pas un classement. Surface-aware et Glicko-2 sont CONSERVÉS dans le
module de comparaison (réévaluables quand l'historique s'allongera), jamais en production
sans preuve.

- ATP et WTA SÉPARÉS : régimes best-of différents (ATP Bo3+Bo5, WTA Bo3), pools disjoints.
- SANS FUITE : notes issues des seuls matchs STRICTEMENT antérieurs ; étiquetage par ORDRE
  CANONIQUE (nom) pour que le modèle n'exploite jamais « la colonne vainqueur ».
- Pas d'avantage domicile (sport neutre). Cold-start : aucune prédiction sous un minimum
  de matchs antérieurs (aucune probabilité fabriquée).

BASELINE À BATTRE = FAVORI AU CLASSEMENT, point-in-time (fréquence de victoire du mieux
classé sur les matchs antérieurs) — la vraie baseline non triviale (~0.64), PAS un 0.5.
La cote de marché (implicite) est reportée pour CONTEXTE, jamais comme gate.

Verdict de maturité MÉCANIQUE (evaluate_maturity) : EXPERIMENTAL tant que les critères
requis ne passent pas ; CLV/freshness non mesurées (aucun live tennis câblé).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from src.agents.quant.betting_engine.live_coverage import live_freshness_capability
from .competition import COMPETITION_IDS
from src.agents.quant.betting_engine.maturity import (
    MaturityObservations,
    ModelSupportDecision,
    evaluate_maturity,
    load_maturity_policy,
)

from .tennis_data_loader import load_tennis_data


@dataclass(frozen=True)
class TennisEloParams:
    init_rating: float
    k_factor: float
    surface_blend: float          # 0.0 en production : gain NON démontré (cf. comparaison)
    min_prior_matches: int        # cold-start : aucune prédiction en-dessous
    notes: str = ""


# Paramètres PROPRES au tennis (FIXES, documentés — jamais fités sur l'évaluation).
# K=24 : valeur Elo usuelle en tennis, fixée A PRIORI (le K dynamique 538 a été mesuré et
# n'améliore pas : Brier holdout supérieur et ECE nettement pire). surface_blend=0.0 :
# la variante surface-aware n'est PAS significativement meilleure (IC apparié contenant 0).
ATP_PARAMS = TennisEloParams(1500.0, 24.0, 0.0, 20,
    "ATP : Elo K=24 ; sans blend de surface (gain non significatif) ; cold-start 20 ; Bo3+Bo5")
WTA_PARAMS = TennisEloParams(1500.0, 24.0, 0.0, 20,
    "WTA : Elo K=24 ; sans blend de surface (gain non significatif) ; cold-start 20 ; Bo3")


def _p(r_a: float, r_b: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(r_a - r_b) / 400.0))


def tennis_ratings_as_of(matches, cutoff, params: TennisEloParams):
    """Notes Elo + nombre de matchs joués, à partir des SEULS matchs STRICTEMENT
    antérieurs à `cutoff` (sans fuite). Même implémentation Elo que le walk-forward —
    réutilisée par l'évaluation live point-in-time (aucune duplication de formule)."""
    ratings: dict[str, float] = {}
    played: Counter = Counter()
    for m in matches:
        if m.tourney_date >= cutoff:
            break                                    # `matches` est trié chronologiquement
        w, l = m.p1_name, m.p2_name
        rw, rl = ratings.get(w, params.init_rating), ratings.get(l, params.init_rating)
        e = _p(rw, rl)
        ratings[w] = rw + params.k_factor * (1.0 - e)
        ratings[l] = rl - params.k_factor * (1.0 - e)
        played[w] += 1
        played[l] += 1
    return ratings, played


def _brier(p: float, y: float) -> float:
    return (p - y) ** 2


def _ece(pairs: list[tuple[float, float]], n_bins: int = 10) -> float | None:
    if not pairs:
        return None
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        bins[min(int(p * n_bins), n_bins - 1)].append((p, y))
    n = len(pairs)
    return round(sum((len(b) / n) * abs(sum(p for p, _ in b) / len(b) - sum(y for _, y in b) / len(b))
                     for b in bins if b), 6)


@dataclass(frozen=True)
class TennisRun:
    model_pairs: list[tuple[float, float]]      # (p_model, y) sur cfirst
    baseline_pairs: list[tuple[float, float]]   # (p_rank_favorite, y)
    market_pairs: list[tuple[float, float]]     # (p_marché implicite, y) — contexte
    fold_years: list[str]
    n_total: int
    n_evaluated: int


def run_tennis_walk_forward(matches, params: TennisEloParams) -> TennisRun:
    glob: dict[str, float] = {}
    surf: dict[tuple[str, str], float] = {}
    played: Counter = Counter()
    fav_wins = decided = 0                        # baseline favori (point-in-time)
    model_pairs: list[tuple[float, float]] = []
    base_pairs: list[tuple[float, float]] = []
    mkt_pairs: list[tuple[float, float]] = []
    years: list[str] = []
    n_eval = 0

    for m in matches:                            # déjà trié chronologiquement
        w, l, s = m.p1_name, m.p2_name, (m.surface or "?")
        rg_w, rg_l = glob.get(w, params.init_rating), glob.get(l, params.init_rating)
        rs_w = surf.get((w, s), params.init_rating)
        rs_l = surf.get((l, s), params.init_rating)
        blend = params.surface_blend
        R_w = blend * rs_w + (1 - blend) * rg_w
        R_l = blend * rs_l + (1 - blend) * rg_l

        eligible = played[w] >= params.min_prior_matches and played[l] >= params.min_prior_matches
        if eligible:
            cfirst, csecond = (w, l) if w < l else (l, w)   # ordre canonique (nom)
            y = 1.0 if cfirst == w else 0.0                 # cfirst a-t-il gagné ?
            p_model = _p(R_w, R_l) if cfirst == w else _p(R_l, R_w)
            model_pairs.append((p_model, y))
            years.append(m.tourney_date.isoformat()[:4])
            n_eval += 1
            # Baseline favori (classement) : proba que cfirst gagne = taux favori si cfirst
            # est le mieux classé, sinon complément. Point-in-time (taux antérieur).
            if m.p1_rank and m.p2_rank and decided >= 100:
                rate = fav_wins / decided
                w_is_fav = m.p1_rank < m.p2_rank            # p1 = vainqueur mieux classé ?
                cfirst_is_fav = (cfirst == w) == w_is_fav
                base_pairs.append((rate if cfirst_is_fav else 1 - rate, y))
            # Marché (contexte) : cote implicite normalisée (dé-vig simple).
            if m.p1_close_odds and m.p2_close_odds:
                iw, il = 1 / m.p1_close_odds, 1 / m.p2_close_odds
                p_w = iw / (iw + il)
                mkt_pairs.append((p_w if cfirst == w else 1 - p_w, y))

        # Mise à jour Elo (issue réelle : w gagne). Global + surface.
        e_w = _p(R_w, R_l)
        glob[w] = rg_w + params.k_factor * (1.0 - e_w)
        glob[l] = rg_l + params.k_factor * (0.0 - (1.0 - e_w))
        surf[(w, s)] = rs_w + params.k_factor * (1.0 - e_w)
        surf[(l, s)] = rs_l + params.k_factor * (0.0 - (1.0 - e_w))
        played[w] += 1
        played[l] += 1
        if m.p1_rank and m.p2_rank:
            decided += 1
            if m.p1_rank < m.p2_rank:
                fav_wins += 1

    return TennisRun(model_pairs, base_pairs, mkt_pairs, years, len(matches), n_eval)


@dataclass(frozen=True)
class TennisAssessment:
    decision: ModelSupportDecision
    observations: MaturityObservations
    run: TennisRun
    metrics: dict


def assess_tennis(tour: str) -> TennisAssessment:
    params = ATP_PARAMS if tour.lower() == "atp" else WTA_PARAMS
    ds = load_tennis_data(tour)
    run = run_tennis_walk_forward(ds.matches, params)
    n = run.n_evaluated
    model_brier = sum(_brier(p, y) for p, y in run.model_pairs) / n
    base_brier = (sum(_brier(p, y) for p, y in run.baseline_pairs) / len(run.baseline_pairs)
                  if run.baseline_pairs else 0.25)
    uniform_brier = sum(_brier(0.5, y) for _, y in run.model_pairs) / n
    best_baseline = min(base_brier, uniform_brier)           # baseline la plus FORTE (favori)
    ece = _ece(run.model_pairs)
    market_brier = (sum(_brier(p, y) for p, y in run.market_pairs) / len(run.market_pairs)
                    if run.market_pairs else None)

    by_year: dict[str, list[float]] = {}
    for (p, y), yr in zip(run.model_pairs, run.fold_years):
        by_year.setdefault(yr, []).append(_brier(p, y))
    year_briers = [sum(v) / len(v) for v in by_year.values()]
    fold_spread = (max(year_briers) - min(year_briers)) if len(year_briers) >= 2 else None

    observations = MaturityObservations(
        n_evaluated=n, n_temporal_folds=len(by_year), calibration_error=ece,
        model_brier=round(model_brier, 6), best_baseline_brier=round(best_baseline, 6),
        data_coverage=round(n / run.n_total, 4) if run.n_total else None,
        mean_data_quality=1.0,
        fold_brier_spread=round(fold_spread, 4) if fold_spread is not None else None,
        clv_status="NOT_YET_MEASURABLE", clv_mean=None,
        live_freshness_status=live_freshness_capability(
            COMPETITION_IDS.get(tour.lower(), f"competition:tennis:{tour.lower()}:tour")))
    decision = evaluate_maturity(
        model_name=f"tennis_{tour.lower()}_moneyline",
        model_version=f"tennis.{tour.lower()}.elo.v0",
        observations=observations, policy=load_maturity_policy())
    metrics = {"model_brier": model_brier, "rank_baseline_brier": base_brier,
               "uniform_brier": uniform_brier, "market_brier": market_brier,
               "beats_rank_baseline": model_brier < base_brier, "ece": ece}
    return TennisAssessment(decision, observations, run, metrics)
