"""Couverture produit : combien du catalogue AXON sait-il réellement évaluer ?

« Tous sports, toutes compétitions » a longtemps voulu dire « les compétitions
qu'on avait codées ». Rien ne mesurait l'écart : le scan disait « 52 rencontres,
0 évaluable » sans jamais dire lesquelles étaient perdues ni pourquoi.

NOT_MEASURED N'EST PAS ZÉRO. Un sport que le scan n'a pas atteint et un sport où
zéro rencontre est évaluable produisent le même `0` — et le premier est un trou
d'instrumentation, le second un trou de modèle. Ils se réparent à des endroits
différents, donc ils portent ici des valeurs différentes : `None` contre `0`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

#: Valeur rendue quand la mesure n'a pas pu être faite. Jamais sérialisée en 0.
NOT_MEASURED = None


@dataclass(frozen=True)
class SportCoverage:
    """Couverture d'UN sport sur un run. Chaque compteur a une définition unique."""

    sport: str
    catalog_events_seen: int | None
    competition_resolved: int
    competition_unresolved: int
    identity_resolved: int
    model_available: int
    evaluated: int
    review_only: int
    actionable: int
    unsupported: int
    blockers: dict[str, int] = field(default_factory=dict)

    def _ratio(self, numerateur: int) -> float | None:
        """`None` quand le dénominateur n'a pas été mesuré — jamais 0.0."""
        if not self.catalog_events_seen:
            return NOT_MEASURED
        return round(numerateur / self.catalog_events_seen, 4)

    @property
    def resolution_rate(self) -> float | None:
        return self._ratio(self.competition_resolved)

    @property
    def evaluation_rate(self) -> float | None:
        return self._ratio(self.evaluated)

    @property
    def actionable_rate(self) -> float | None:
        return self._ratio(self.actionable)

    def as_dict(self) -> dict:
        return {
            "sport": self.sport,
            "catalog_events_seen": self.catalog_events_seen,
            "competition_resolved": self.competition_resolved,
            "competition_unresolved": self.competition_unresolved,
            "identity_resolved": self.identity_resolved,
            "model_available": self.model_available,
            "evaluated": self.evaluated,
            "review_only": self.review_only,
            "actionable": self.actionable,
            "unsupported": self.unsupported,
            "resolution_rate": self.resolution_rate,
            "evaluation_rate": self.evaluation_rate,
            "actionable_rate": self.actionable_rate,
            "blockers": dict(self.blockers),
        }


@dataclass(frozen=True)
class CatalogCoverage:
    """Couverture d'un run entier, sport par sport, plus le global."""

    measured_at: datetime
    window_start: datetime | None
    window_end: datetime | None
    run_id: str | None
    par_sport: tuple[SportCoverage, ...]
    #: `False` quand le catalogue brut n'a pas pu être lu : les totaux sont alors
    #: des minorants, et le dire vaut mieux que publier un pourcentage faux.
    catalog_reachable: bool = True

    @property
    def total_catalog_events(self) -> int | None:
        vus = [s.catalog_events_seen for s in self.par_sport
               if s.catalog_events_seen is not None]
        return sum(vus) if vus else NOT_MEASURED

    @property
    def total_evaluated(self) -> int:
        return sum(s.evaluated for s in self.par_sport)

    @property
    def total_actionable(self) -> int:
        return sum(s.actionable for s in self.par_sport)

    @property
    def global_coverage(self) -> float | None:
        total = self.total_catalog_events
        if not total:
            return NOT_MEASURED
        return round(self.total_evaluated / total, 4)

    def as_dict(self) -> dict:
        return {
            "measured_at": self.measured_at.isoformat(),
            "window_start": None if self.window_start is None else self.window_start.isoformat(),
            "window_end": None if self.window_end is None else self.window_end.isoformat(),
            "run_id": self.run_id,
            "catalog_reachable": self.catalog_reachable,
            "total_catalog_events": self.total_catalog_events,
            "total_evaluated": self.total_evaluated,
            "total_actionable": self.total_actionable,
            "global_coverage": self.global_coverage,
            "sports": [s.as_dict() for s in self.par_sport],
        }


#: Statuts de trace signifiant « la compétition n'a pas été rattachée ».
_COMPETITION_NON_RESOLUE = frozenset({"COMPETITION_NOT_RESOLVED", "EVENT_NOT_RESOLVED"})
#: Statuts signifiant « identité et compétition OK, mais aucun modèle applicable ».
_SANS_MODELE = frozenset({"SPORT_NOT_SUPPORTED", "MODEL_NOT_SUPPORTED",
                          "COMPETITION_NOT_COVERED"})


def mesurer(observability, *, response=None, evidence=None,
            measured_at: datetime | None = None) -> CatalogCoverage:
    """Dérive la couverture d'un run. Ne calcule rien qui ne soit pas observé.

    `catalog_events_seen` vaut `None` pour un sport dont le scan n'a rapporté
    aucun compte — pas `0`, qui affirmerait un catalogue vide.
    """
    from datetime import timezone

    traces = tuple(getattr(observability, "traces", ()) or ())
    telemetrie = getattr(observability, "telemetry", None)
    par_sport_traces: dict[str, list] = defaultdict(list)
    for trace in traces:
        par_sport_traces[trace.sport].append(trace)

    # Rencontres du catalogue par sport, telles que le scan les a comptées.
    vus_par_sport: dict[str, int] = dict(getattr(telemetrie, "events_seen_by_sport", {}) or {})

    review_ids = {getattr(c, "event_id", None)
                  for c in (getattr(response, "review_candidates", ()) or ())}
    actionable_ids: set = set()
    for portefeuille in (getattr(response, "portfolios", ()) or ()):
        for ligne in getattr(portefeuille, "lines", ()) or ():
            for jambe in getattr(ligne, "legs", ()) or ():
                actionable_ids.add(getattr(jambe, "event_id", None))

    sports: list[SportCoverage] = []
    for sport in sorted(set(par_sport_traces) | set(vus_par_sport)):
        liste = par_sport_traces.get(sport, [])
        evalues = [t for t in liste if t.evaluated]
        non_resolues = [t for t in liste if t.status in _COMPETITION_NON_RESOLUE]
        sans_modele = [t for t in liste if t.status in _SANS_MODELE]
        ids = {t.event_id for t in liste if t.event_id}
        sports.append(SportCoverage(
            sport=sport,
            catalog_events_seen=vus_par_sport.get(sport, len(liste) or NOT_MEASURED),
            competition_resolved=sum(1 for t in liste if t.competition_id),
            competition_unresolved=len(non_resolues),
            identity_resolved=sum(1 for t in liste if t.event_id),
            model_available=len(liste) - len(sans_modele) - len(non_resolues),
            evaluated=len(evalues),
            review_only=len(ids & {i for i in review_ids if i}),
            actionable=len(ids & {i for i in actionable_ids if i}),
            unsupported=len(liste) - len(evalues),
            blockers=dict(Counter(t.status for t in liste if not t.evaluated)),
        ))

    return CatalogCoverage(
        measured_at=measured_at or datetime.now(timezone.utc),
        window_start=getattr(evidence, "window_start", None),
        window_end=getattr(evidence, "window_end", None),
        run_id=getattr(evidence, "run_id", None),
        par_sport=tuple(sports),
        catalog_reachable=bool(traces) or bool(vus_par_sport),
    )


def rendre_texte(c: CatalogCoverage) -> list[str]:
    """Rendu lisible. `n/m` marque explicitement une mesure absente."""
    def n(v) -> str:
        return "n/m" if v is None else str(v)

    def pct(v) -> str:
        return "n/m" if v is None else f"{v * 100:.1f} %"

    if not c.catalog_reachable:
        return ["AXON CATALOG COVERAGE", "",
                "  NOT_MEASURED — le catalogue n'a pas pu être lu sur ce run.",
                "  Aucun pourcentage n'est publié : il serait extrapolé."]

    lignes = ["AXON CATALOG COVERAGE",
              f"  fenêtre : {c.window_start} → {c.window_end}", ""]
    entete = (f"  {'sport':<18}{'catalog':>9}{'résolu':>9}{'évalué':>9}"
              f"{'review':>9}{'action.':>9}{'non éval.':>11}{'couv.':>9}")
    lignes += [entete, "  " + "-" * (len(entete) - 2)]
    for s in c.par_sport:
        lignes.append(
            f"  {s.sport:<18}{n(s.catalog_events_seen):>9}{s.competition_resolved:>9}"
            f"{s.evaluated:>9}{s.review_only:>9}{s.actionable:>9}"
            f"{s.unsupported:>11}{pct(s.evaluation_rate):>9}")
        for code, nombre in sorted(s.blockers.items(), key=lambda kv: -kv[1])[:3]:
            lignes.append(f"      · {nombre:4d}  {code}")
    lignes += ["",
               f"  GLOBAL : {n(c.total_catalog_events)} rencontre(s) au catalogue · "
               f"{c.total_evaluated} évaluée(s) · {c.total_actionable} actionnable(s) "
               f"· couverture {pct(c.global_coverage)}"]
    return lignes
