"""Métriques d'évaluation 1X2 — AUTO-DESCRIPTIVES.

Chaque métrique porte sa convention DANS sa sortie (et donc dans l'enregistrement
persisté), pas seulement en commentaire : le Brier déclare sa convention (somme
sur les 3 classes) et sa plage ; la log loss déclare son clipping et sa base. Un
score sans sa convention n'est pas reproductible.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

CLASSES = ("home", "draw", "away")

# Conventions — reproduites dans chaque sortie de métrique.
BRIER_CONVENTION = "sum_over_classes"   # Σ_i (p_i − o_i)²  (par événement), plage [0, 2]
LOG_LOSS_CLIP_EPSILON = 1e-15           # p ∈ [eps, 1−eps] avant log (convention sklearn)
LOG_LOSS_BASE = "e"                     # logarithme naturel

Prediction = tuple[dict[str, float], str]   # (probabilités {home,draw,away}, issue réelle)


def brier_score(prob: dict[str, float], outcome: str) -> float:
    """Brier multiclasses d'UN événement : Σ sur les 3 classes de (p − o)²."""
    return sum((prob[c] - (1.0 if c == outcome else 0.0)) ** 2 for c in CLASSES)


def log_loss(prob: dict[str, float], outcome: str, eps: float = LOG_LOSS_CLIP_EPSILON) -> float:
    """Log loss d'UN événement, avec clipping numérique (jamais log(0))."""
    p = min(max(prob[outcome], eps), 1.0 - eps)
    return -math.log(p)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(predictions: Sequence[Prediction]) -> dict:
    """Métriques agrégées auto-descriptives sur une liste de prédictions."""
    n = len(predictions)
    outcome_dist = Counter(o for _, o in predictions)
    briers = [brier_score(p, o) for p, o in predictions]
    lls = [log_loss(p, o) for p, o in predictions]
    per_class = {
        c: _mean([(p[c] - (1.0 if o == c else 0.0)) ** 2 for p, o in predictions])
        for c in CLASSES
    }
    return {
        "n_evaluated": n,
        "outcome_distribution": {c: outcome_dist.get(c, 0) for c in CLASSES},
        "brier": {
            "value": round(_mean(briers), 6),
            "convention": BRIER_CONVENTION,      # <- convention stockée dans le résultat
            "range": [0, 2],
            "aggregation": "mean_over_events",
        },
        "log_loss": {
            "value": round(_mean(lls), 6),
            "clip_epsilon": LOG_LOSS_CLIP_EPSILON,  # <- clipping stocké dans le résultat
            "base": LOG_LOSS_BASE,
            "aggregation": "mean_over_events",
        },
        "brier_per_class": {c: round(v, 6) for c, v in per_class.items()},
    }


def uniform_baseline(outcomes: Sequence[str]) -> dict:
    """Baseline probabilités uniformes (1/3, 1/3, 1/3) — sans fuite."""
    uniform = {c: 1.0 / 3.0 for c in CLASSES}
    return evaluate([(uniform, o) for o in outcomes])


def calibration_bin_counts(predictions: Sequence[Prediction], n_bins: int = 10) -> dict:
    """Compte des observations par bin de probabilité (par classe).

    Sert à JUGER si une calibration curve est publiable : des bins trop peu
    peuplés ne prouvent rien. On expose les comptes, jamais une courbe instable.
    """
    edges = [round(i / n_bins, 4) for i in range(n_bins + 1)]
    counts = [0] * n_bins
    for prob, _ in predictions:
        for c in CLASSES:
            b = min(int(prob[c] * n_bins), n_bins - 1)
            counts[b] += 1
    return {"n_bins": n_bins, "edges": edges, "counts": counts,
            "note": "comptes bruts ; courbe non publiée si bins trop peu peuplés"}
