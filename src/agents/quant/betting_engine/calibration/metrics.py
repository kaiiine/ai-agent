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


def _classes(classes: Sequence[str] | None) -> tuple[str, ...]:
    """Le jeu de classes du marché évalué. Défaut : le 1X2 historique.

    Ces métriques ne sont pas propres au 1X2 — un Plus/Moins a deux classes, un
    score exact en a trente-sept. Le paramètre existe pour qu'il n'y ait qu'UNE
    implémentation du Brier et de l'ECE dans le moteur : deux implémentations
    finiraient par produire deux nombres différents pour la même chose, et le
    jour où elles divergent, c'est la comparaison entre marchés qui ment.
    """
    return tuple(classes) if classes else CLASSES


def brier_score(prob: dict[str, float], outcome: str,
                classes: Sequence[str] | None = None) -> float:
    """Brier multiclasses d'UN événement : Σ sur les classes de (p − o)²."""
    return sum((prob[c] - (1.0 if c == outcome else 0.0)) ** 2 for c in _classes(classes))


def log_loss(prob: dict[str, float], outcome: str, eps: float = LOG_LOSS_CLIP_EPSILON,
             classes: Sequence[str] | None = None) -> float:
    """Log loss d'UN événement, avec clipping numérique (jamais log(0))."""
    p = min(max(prob[outcome], eps), 1.0 - eps)
    return -math.log(p)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(predictions: Sequence[Prediction],
             classes: Sequence[str] | None = None) -> dict:
    """Métriques agrégées auto-descriptives sur une liste de prédictions."""
    cls = _classes(classes)
    n = len(predictions)
    outcome_dist = Counter(o for _, o in predictions)
    briers = [brier_score(p, o, cls) for p, o in predictions]
    lls = [log_loss(p, o, classes=cls) for p, o in predictions]
    per_class = {
        c: _mean([(p[c] - (1.0 if o == c else 0.0)) ** 2 for p, o in predictions])
        for c in cls
    }
    return {
        "n_evaluated": n,
        "classes": list(cls),
        "outcome_distribution": {c: outcome_dist.get(c, 0) for c in cls},
        "brier": {
            "value": round(_mean(briers), 6),
            "convention": BRIER_CONVENTION,      # <- convention stockée dans le résultat
            # La plage du Brier dépend du NOMBRE de classes : [0, 2] pour k ≥ 2
            # avec la convention « somme sur les classes ». La borne est donc
            # rapportée, jamais supposée par le lecteur.
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


def uniform_baseline(outcomes: Sequence[str],
                     classes: Sequence[str] | None = None) -> dict:
    """Baseline probabilités uniformes (1/k sur k classes) — sans fuite."""
    cls = _classes(classes)
    uniform = {c: 1.0 / len(cls) for c in cls}
    return evaluate([(uniform, o) for o in outcomes], classes=cls)


def expected_calibration_error(predictions: Sequence[Prediction], n_bins: int = 10,
                               classes: Sequence[str] | None = None) -> dict:
    """ECE mutualisée sur les classes — MESURE de calibration, pas accuracy.

    Pour chaque prédiction, chaque classe fournit une paire (proba prédite,
    indicateur 0/1). Les paires sont regroupées par bin de proba ; l'ECE est la
    moyenne pondérée des écarts |proba moyenne − fréquence réelle| par bin. Une
    proba de 0,70 « bien calibrée » se réalise ~70 % du temps → écart faible.

    Auto-descriptive (convention dans la sortie). Mesurée hors échantillon quand
    `predictions` sont des prédictions walk-forward point-in-time.
    """
    cls = _classes(classes)
    pairs = [
        (prob[c], 1.0 if c == outcome else 0.0)
        for prob, outcome in predictions
        for c in cls
    ]
    n = len(pairs)
    if n == 0:
        return {"ece": None, "n_bins": n_bins, "n_pairs": 0, "per_bin": [],
                "convention": "pooled_over_classes_abs_gap_weighted"}
    sums = [0.0] * n_bins
    preds = [0.0] * n_bins
    counts = [0] * n_bins
    for p, y in pairs:
        b = min(int(p * n_bins), n_bins - 1)
        sums[b] += y
        preds[b] += p
        counts[b] += 1
    ece = 0.0
    per_bin = []
    for i in range(n_bins):
        if counts[i] == 0:
            per_bin.append({"bin": i, "count": 0, "mean_pred": None, "empirical": None})
            continue
        mean_pred = preds[i] / counts[i]
        empirical = sums[i] / counts[i]
        ece += (counts[i] / n) * abs(mean_pred - empirical)
        per_bin.append({"bin": i, "count": counts[i],
                        "mean_pred": round(mean_pred, 6), "empirical": round(empirical, 6)})
    return {"ece": round(ece, 6), "n_bins": n_bins, "n_pairs": n, "per_bin": per_bin,
            "convention": "pooled_over_classes_abs_gap_weighted"}


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
