"""Calibrateur de probabilités — histogram binning, simple et AUDITABLE (PRD §7.1).

Choix délibéré du calibrateur le plus simple et inspectable (pas d'isotonic/Platt
« sophistiqué » : cf. consigne — méthode simple, impossible à fitter sur
l'observation qu'elle évalue). Un seul jeu de bins MUTUALISÉ sur les trois issues
1X2 (elles vivent dans le même espace [0,1]) : maximise le nombre d'observations
par bin, ce qui compte quand les données sont rares.

Point-in-time : ce module ne connaît pas le temps. C'est l'APPELANT (walk_forward)
qui ne lui passe QUE des paires strictement antérieures au cutoff — le calibrateur
ajusté à T n'a jamais vu l'issue qu'il corrige. En dessous de `min_samples` paires,
il reste NON ajusté et applique l'identité (jamais une correction fabriquée sur un
échantillon squelettique).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

CLASSES = ("home", "draw", "away")
Prediction = tuple[dict[str, float], str]     # (probabilités {home,draw,away}, issue réelle)

DEFAULT_N_BINS = 10
DEFAULT_MIN_SAMPLES = 50                       # paires (issue, proba) minimales avant d'oser corriger


def _pooled_pairs(predictions: Sequence[Prediction]) -> list[tuple[float, float]]:
    """(proba prédite, indicateur 0/1) mutualisés sur les 3 classes."""
    out: list[tuple[float, float]] = []
    for prob, outcome in predictions:
        for c in CLASSES:
            out.append((prob[c], 1.0 if c == outcome else 0.0))
    return out


def _bin_index(p: float, n_bins: int) -> int:
    return min(int(p * n_bins), n_bins - 1)


@dataclass(frozen=True)
class HistogramBinningCalibrator:
    n_bins: int
    min_samples: int
    bin_freq: tuple[float | None, ...]         # fréquence empirique par bin (None si bin vide)
    fitted: bool
    n_train_pairs: int

    @classmethod
    def unfitted(cls, n_bins: int = DEFAULT_N_BINS, min_samples: int = DEFAULT_MIN_SAMPLES) -> "HistogramBinningCalibrator":
        return cls(n_bins, min_samples, tuple([None] * n_bins), False, 0)

    @classmethod
    def fit(
        cls,
        prior_predictions: Sequence[Prediction],
        n_bins: int = DEFAULT_N_BINS,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> "HistogramBinningCalibrator":
        pairs = _pooled_pairs(prior_predictions)
        if len(pairs) < min_samples:
            # Échantillon trop mince : on n'invente aucune correction (identité).
            return cls(n_bins, min_samples, tuple([None] * n_bins), False, len(pairs))
        sums = [0.0] * n_bins
        counts = [0] * n_bins
        for p, y in pairs:
            b = _bin_index(p, n_bins)
            sums[b] += y
            counts[b] += 1
        bin_freq = tuple(
            (sums[i] / counts[i]) if counts[i] > 0 else None for i in range(n_bins)
        )
        return cls(n_bins, min_samples, bin_freq, True, len(pairs))

    def apply(self, prob: dict[str, float]) -> dict[str, float]:
        """Mappe chaque proba de classe via la fréquence empirique de son bin, puis
        renormalise à somme 1. Non ajusté → identité. Bin vide → proba brute conservée
        (jamais 0). Somme dégénérée → identité (jamais de division par 0)."""
        if not self.fitted:
            return dict(prob)
        mapped: dict[str, float] = {}
        for c in CLASSES:
            b = _bin_index(prob[c], self.n_bins)
            f = self.bin_freq[b]
            mapped[c] = f if f is not None else prob[c]     # bin vide → brut, jamais fabriqué
        total = sum(mapped.values())
        if total <= 0:
            return dict(prob)                                # dégénéré → identité
        return {c: mapped[c] / total for c in CLASSES}
