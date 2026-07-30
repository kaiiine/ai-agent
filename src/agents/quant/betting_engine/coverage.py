"""Observabilité de couverture (§11) : à partir d'un `LiveEvaluationBatch`, mesure
ce qui a été DÉCOUVERT, ce qui est ÉVALUABLE, et ce qui ne l'est pas — AVEC la raison
typée. Rend visible la distinction `catalogue coverage ≠ model coverage` : un catalogue
large n'implique pas une couverture de modèle. Aucune donnée fabriquée : tout dérive
des statuts réels d'évaluation (`LiveEvaluationStatus`), jamais d'une supposition.

Un sport/compétition non supporté n'arrête JAMAIS le run : il apparaît comme
`events_not_evaluable` avec sa raison, pendant que les autres restent évaluables.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .live_evaluation import LiveEvaluationStatus


@dataclass(frozen=True)
class CompetitionCoverage:
    competition: str
    discovered: int
    evaluable: int                       # statut EVALUATED
    statuses: dict[str, int]             # statut -> compte (raisons de non-évaluabilité)


@dataclass(frozen=True)
class CoverageReport:
    sport: str
    events_discovered: int
    events_evaluable: int                # >=1 modèle a réellement produit une évaluation
    events_not_evaluable: int
    by_status: dict[str, int]            # statut typé -> compte (raison de couverture)
    by_competition: tuple[CompetitionCoverage, ...]

    @property
    def evaluable_ratio(self) -> float:
        return self.events_evaluable / self.events_discovered if self.events_discovered else 0.0


def summarize_batch(batch, sport: str) -> CoverageReport:
    """Résumé de couverture d'un batch d'évaluation (toutes compétitions découvertes)."""
    by_status: Counter = Counter()
    per_comp_status: dict[str, Counter] = {}
    per_comp_total: Counter = Counter()

    for raw_event, result in batch.results:
        status = result.status.value
        by_status[status] += 1
        competition = raw_event.competition or "(compétition inconnue)"
        per_comp_status.setdefault(competition, Counter())[status] += 1
        per_comp_total[competition] += 1

    evaluated = LiveEvaluationStatus.EVALUATED.value
    discovered = len(batch.results)
    evaluable = by_status.get(evaluated, 0)

    competitions = tuple(sorted(
        (CompetitionCoverage(
            competition=comp, discovered=per_comp_total[comp],
            evaluable=per_comp_status[comp].get(evaluated, 0), statuses=dict(per_comp_status[comp]))
         for comp in per_comp_status),
        key=lambda c: (-c.discovered, c.competition)))

    return CoverageReport(
        sport=sport, events_discovered=discovered, events_evaluable=evaluable,
        events_not_evaluable=discovered - evaluable, by_status=dict(by_status),
        by_competition=competitions)
