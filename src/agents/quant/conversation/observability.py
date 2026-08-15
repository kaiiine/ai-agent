"""Observabilité d'un run — ADDITIVE. Aucune décision, aucune formule.

Le run rendait six nombres : 757 scannés, 99 dans la fenêtre, 60 évalués,
REVIEW_CANDIDATES, 0 portefeuille, 0 mise. Exacts, et pourtant illisibles :
« 7 sports scannés » quand Winamax en expose 29, « 60 évalués » qui comptait des
SÉLECTIONS et non des rencontres, et un écart de 39 qu'aucune décomposition ne
justifiait.

Ce module ne calcule rien de neuf. Il assemble ce que le domaine a déjà produit
et que le rendu jetait : le statut typé de chaque refus, le sport et la
compétition de chaque rencontre, l'ordre des portes tel qu'il a réellement été
parcouru, et les critères de maturité de chaque modèle utilisé.

Deux règles de lecture :

- **Un compteur, une définition.** Un événement compté « dans la fenêtre » ne
  peut plus être décrit comme exclu hors fenêtre. L'identité est vérifiée par
  construction, pas par commentaire.
- **Une absence n'est pas un zéro.** `freshness_score=None` veut dire non
  mesurée ; l'écrire `0` en ferait une mesure, et une mauvaise.
"""

from __future__ import annotations

import functools

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

#: Ce que le renderer doit écrire à la place d'une valeur absente. Jamais `0`.
NON_MESURE = "NON MESURÉ"
INDISPONIBLE = "INDISPONIBLE"
NON_APPLICABLE = "NON APPLICABLE"


@dataclass(frozen=True)
class EventTrace:
    """Le chemin d'UNE rencontre, tel que le domaine l'a parcouru.

    `status` et `reason` viennent de `LiveEvaluationResult` — jamais reconstruits
    par déduction depuis ce qui manque en sortie.
    """

    bookmaker_event_id: str
    sport: str
    competition_label: str
    kickoff: datetime | None
    status: str
    reason: str
    event_id: str | None = None
    competition_id: str | None = None
    selections: int = 0
    freshness_score: float | None = None

    @property
    def evaluated(self) -> bool:
        return self.status == "EVALUATED"


@dataclass(frozen=True)
class ScanTelemetry:
    """Ce que le SCAN a vu, avant que l'évaluation ne commence.

    Le catalogue disparaissait entièrement : seuls deux entiers en sortaient. Or
    c'est là que se joue la différence entre « Winamax n'expose pas ce sport » et
    « nous n'avons pas de modèle pour ce sport » — deux situations que le même
    nombre décrivait.
    """

    catalog_sports: Mapping[int, str] = field(default_factory=dict)
    scanned_sports: tuple[str, ...] = ()
    catalog_events_total: int = 0
    events_outside_window: int = 0
    events_inside_window: int = 0
    #: sport -> libellés de compétition rencontrés dans le scan (hors fenêtre inclus)
    catalog_competitions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: sport -> rencontres vues au CATALOGUE, fenêtre comprise ou non. Sans ce
    #: compte, la couverture d'un sport se calcule sur les seules rencontres
    #: parvenues jusqu'à l'évaluation — un dénominateur qui exclut précisément ce
    #: qu'on cherche à mesurer, donc un taux flatteur par construction.
    #: Vide = NON MESURÉ, jamais « catalogue vide ».
    events_seen_by_sport: Mapping[str, int] = field(default_factory=dict)
    #: sport -> panne du scan (type + message). Un sport ICI n'a PAS été
    #: interrogé : son absence du classement ne veut pas dire qu'il n'offrait
    #: rien. Sans ce champ, une coupure réseau sur une branche se lisait comme
    #: « aucune opportunité » sur cette branche — la pire des deux erreurs, parce
    #: qu'elle est silencieuse.
    scan_failures: Mapping[str, str] = field(default_factory=dict)
    #: Marchés RÉELLEMENT rapportés, avant et après la récupération par événement.
    #: L'écart est la mesure de ce que la page catalogue ne montre pas : elle ne
    #: sert qu'un marché par rencontre, et s'en contenter revenait à déclarer que
    #: le bookmaker n'en propose qu'un. `0` = non mesuré (aucun scan).
    markets_from_catalog: int = 0
    markets_after_event_pages: int = 0
    events_market_enriched: int = 0
    #: Rencontres dont la page n'a PAS été demandée (aucun modèle ne peut les
    #: évaluer), et le nombre de marchés que la source déclare pour elles. Ce
    #: second compte est ce qui empêche « page non lue » de se confondre avec
    #: « rencontre à un seul marché ».
    events_without_market_page: int = 0
    declared_markets_not_fetched: int = 0
    #: identifiant d'événement -> panne de sa page. Ces rencontres restent
    #: évaluées sur leur marché de catalogue : une page absente n'est pas un
    #: événement absent.
    market_fetch_failures: Mapping[str, str] = field(default_factory=dict)
    #: L'entonnoir MARCHÉ du run (`markets.event_pricing.MarketFunnel`), agrégé
    #: sur tous les événements évalués : combien de marchés vus, canonicalisés,
    #: couverts par un modèle, pricés — et sous quel motif les autres sont tombés.
    #: `None` = aucun événement n'a atteint l'étape marché, ce qui n'est pas la
    #: même chose qu'un entonnoir à zéro.
    market_funnel: object | None = None

    @property
    def sports_effectivement_scannes(self) -> tuple[str, ...]:
        """Les sports demandés dont la source a répondu. Le dénominateur honnête
        de toute couverture : `scanned_sports` inclut ceux qui ont échoué."""
        return tuple(s for s in self.scanned_sports if s not in self.scan_failures)


@dataclass(frozen=True)
class ModelReadiness:
    """Maturité d'UN modèle, telle que `evaluate_maturity` l'a rendue.

    Proximité de MATURITÉ, jamais proximité d'un pari : « 6 critères requis sur 8 »
    décrit l'état d'un modèle, pas la sûreté d'une sélection.
    """

    model_name: str
    model_version: str
    sport: str
    status: str
    passed: tuple[str, ...]
    failed: tuple[str, ...]
    not_measurable: tuple[str, ...]
    monitoring: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...]
    #: Avancement de la CLV : rencontres indépendantes collectées et seuil requis.
    #: Additifs et purement descriptifs — « bloqué par la CLV » ne dit pas s'il
    #: manque une rencontre ou vingt-neuf, et c'est la seule chose qu'on puisse
    #: réellement suivre dans le temps.
    clv_events: int | None = None
    clv_required: int | None = None
    #: Détail affichable de chaque critère requis : (nom, verdict, explication).
    criteres: tuple[tuple[str, str, str], ...] = ()

    @property
    def required_total(self) -> int:
        return len(self.passed) + len(self.failed) + len(self.not_measurable)


@dataclass(frozen=True)
class RunObservability:
    """Vue complète d'un run. Assemblée, jamais inférée."""

    telemetry: ScanTelemetry
    traces: tuple[EventTrace, ...]
    model_capable_sports: tuple[str, ...]
    #: `CandidateEvaluation` de l'Advisor, statut par statut
    policy_evaluations: tuple[Any, ...] = ()
    readiness: tuple[ModelReadiness, ...] = ()
    #: (event_id, market_id, selection) -> `AdaptedEvaluation`. Le générateur
    #: consomme `no_vig_probability` pour calculer l'edge mais ne le conserve pas
    #: sur le candidat ; `observed_at` non plus. Cette table les RETROUVE par
    #: jointure sur la clé du marché — une lecture, jamais un recalcul.
    adapted_by_key: Mapping[tuple[str, str, str], Any] = field(default_factory=dict)

    #: `event_id` -> faits externes. Attaché à l'OBSERVABILITÉ et jamais au
    #: candidat : une feature Internet ne doit pas pouvoir voyager dans un objet
    #: que l'Advisor lit. La séparation est structurelle, pas conventionnelle.
    internet_features: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)

    #: Le classement produit multi-marché (`market_review.MarketReview`) : global,
    #: par événement, et les non-comparables avec leur motif. `None` = non
    #: construit sur ce run. Aucune décision d'argent n'en dépend — le
    #: portefeuille décide, ce classement montre.
    review: Any = None

    def adapted_for(self, candidate: Any) -> Any | None:
        return self.adapted_by_key.get(
            (candidate.event_id, candidate.market_id, candidate.selection))

    def features_for(self, candidate: Any) -> tuple[Any, ...]:
        return self.internet_features.get(candidate.event_id, ())

    # ── Couverture, niveau par niveau ─────────────────────────────────────────
    @property
    def sports_in_window(self) -> tuple[str, ...]:
        return tuple(sorted({t.sport for t in self.traces}))

    @property
    def sports_evaluated(self) -> tuple[str, ...]:
        return tuple(sorted({t.sport for t in self.traces if t.evaluated}))

    @property
    def competitions_in_window(self) -> dict[str, tuple[str, ...]]:
        par_sport: dict[str, set[str]] = defaultdict(set)
        for trace in self.traces:
            par_sport[trace.sport].add(trace.competition_label)
        return {s: tuple(sorted(c)) for s, c in sorted(par_sport.items())}

    @property
    def competitions_resolved(self) -> tuple[str, ...]:
        return tuple(sorted({t.competition_id for t in self.traces if t.competition_id}))

    @property
    def competitions_evaluated(self) -> tuple[str, ...]:
        return tuple(sorted({t.competition_id for t in self.traces
                             if t.evaluated and t.competition_id}))

    # ── Compteurs : une définition chacun ─────────────────────────────────────
    @property
    def events_evaluated(self) -> int:
        """RENCONTRES, pas sélections. Le nombre affiché jusqu'ici comptait les
        sélections — deux ou trois par match — et ne pouvait donc pas se
        raccorder au nombre d'événements de la fenêtre."""
        return sum(1 for t in self.traces if t.evaluated)

    @property
    def selections_evaluated(self) -> int:
        return sum(t.selections for t in self.traces)

    @property
    def pre_evaluation_refusals(self) -> dict[str, int]:
        """Refus AVANT le modèle, par statut typé du Betting Engine."""
        return dict(Counter(t.status for t in self.traces if not t.evaluated))

    @property
    def counters(self) -> dict[str, int]:
        return {
            "catalog_events_total": self.telemetry.catalog_events_total,
            "events_outside_window": self.telemetry.events_outside_window,
            "events_inside_window": self.telemetry.events_inside_window,
            **{f"events_{code.lower()}": n
               for code, n in sorted(self.pre_evaluation_refusals.items())},
            "events_evaluated": self.events_evaluated,
            "selections_evaluated": self.selections_evaluated,
        }

    def counters_balance(self) -> tuple[bool, str]:
        """L'identité vérifiable : dans la fenêtre = refus avant évaluation + évalués.

        Sans elle, un écart de 39 se justifie par « par exemple hors fenêtre ou
        données insuffisantes » — une phrase qui recompte hors fenêtre des
        événements déjà comptés dedans, et qui ne peut donc jamais être fausse.
        """
        refus = sum(self.pre_evaluation_refusals.values())
        attendu = self.telemetry.events_inside_window
        obtenu = refus + self.events_evaluated
        if attendu == obtenu:
            return True, f"{attendu} = {refus} refusés + {self.events_evaluated} évalués"
        return False, (f"incohérence : {attendu} dans la fenêtre ≠ {refus} refusés "
                       f"+ {self.events_evaluated} évalués")

    # ── Matrice des bloqueurs, par COUCHE ─────────────────────────────────────
    def blocker_matrix(self) -> dict[str, dict[str, int]]:
        """Quatre couches distinctes, jamais fondues sous « autres ».

        Un `MODEL_NOT_SUPPORTED` de l'Advisor et un `SPORT_NOT_SUPPORTED` du
        moteur se réparent à des endroits différents ; les additionner produit un
        nombre qui ne désigne aucune action.
        """
        moteur = self.pre_evaluation_refusals

        advisor: Counter = Counter()
        maturite: Counter = Counter()
        for evaluation in self.policy_evaluations:
            for reason in evaluation.policy_reasons:
                advisor[reason] += 1
        for readiness in self.readiness:
            for critere in readiness.failed:
                maturite[f"{critere}:FAIL"] += 1
            for critere in readiness.not_measurable:
                maturite[f"{critere}:NOT_MEASURABLE"] += 1

        statuts = Counter(e.status.value for e in self.policy_evaluations)

        return {
            "refus avant modèle (Betting Engine)": dict(sorted(moteur.items())),
            "statut Advisor": dict(sorted(statuts.items())),
            "raisons Advisor": dict(sorted(advisor.items())),
            "critères de maturité en échec": dict(sorted(maturite.items())),
        }


def primary_blocker(evaluation: Any) -> str:
    """Le PREMIER bloqueur, dans l'ordre des portes du domaine.

    `evaluate_eligibility` court-circuite au premier rejet dur (raison unique) et
    accumule les raisons de revue dans l'ordre de ses portes. `policy_reasons[0]`
    est donc le premier bloqueur PAR CONSTRUCTION — le renderer n'a aucun ordre à
    inventer, et ne peut pas diverger de celui qui a réellement été appliqué.
    """
    return evaluation.policy_reasons[0] if evaluation.policy_reasons else NON_APPLICABLE


# ── Assemblage ────────────────────────────────────────────────────────────────
def build_traces(batch_results: Sequence[tuple[Any, Any]]) -> tuple[EventTrace, ...]:
    """Un `EventTrace` par rencontre, depuis `LiveEvaluationBatch.results`.

    On part du batch de DOMAINE et non de l'`AdaptedBatch` : ce dernier expose
    une `SkippedEvaluation` réduite à des identifiants, sans sport ni compétition.
    Un refus n'y est donc attribuable à aucun sport — précisément ce qu'il faut
    savoir pour agir dessus.
    """
    traces: list[EventTrace] = []
    for raw_event, result in batch_results:
        canonical = getattr(result, "canonical_event", None)
        traces.append(EventTrace(
            bookmaker_event_id=raw_event.bookmaker_event_id,
            sport=raw_event.sport,
            competition_label=raw_event.competition or INDISPONIBLE,
            kickoff=raw_event.start_time,
            status=result.status.value,
            reason=result.reason,
            event_id=getattr(canonical, "event_id", None),
            competition_id=getattr(canonical, "competition_id", None),
            selections=len(result.predictions or {}),
            freshness_score=result.freshness_score,
        ))
    return tuple(traces)


#: sport -> clé d'évaluateur de `readiness_cli._ASSESSORS`. Un sport absent n'a
#: pas de readiness calculable ici : il est OMIS, jamais rendu « inconnu = 0 ».
_READINESS_KEYS: dict[str, tuple[str, ...]] = {
    "football": ("fl1",),
    "basketball": ("nba",),
    "baseball": ("mlb",),
    "american_football": ("nfl",),
    "volleyball": ("volley",),
    "hockey": ("nhl",),
    "tennis": ("atp", "wta"),
}


def collect_readiness(sports: Sequence[str]) -> tuple[ModelReadiness, ...]:
    """Maturité des modèles RÉELLEMENT utilisés dans ce run.

    Chaque évaluation rejoue une validation walk-forward sur son dataset embarqué
    (~1,5 s pour le tennis, ~3 s pour quatre sports). On ne la lance donc que pour
    les sports présents : c'est une mesure du modèle, pas du run, et elle ne
    change aucune décision.

    Le résultat est MÉMORISÉ pour la durée du processus. Un modèle et son dataset
    embarqué ne bougent pas entre deux tours de conversation ; recalculer la même
    validation à chaque question payait plusieurs secondes pour un résultat
    identique au caractère près. C'est la même mesure, pas une approximation.

    L'historique de cotes, LUI, grandit — la collecte tourne en tâche de fond. Son
    empreinte entre donc dans la clé de mémorisation : sans elle, un processus de
    longue durée afficherait indéfiniment la progression CLV du premier tour, et
    l'utilisateur croirait la collecte arrêtée.
    """
    return _readiness_memorisee(tuple(sorted(set(sports))), _empreinte_historique())


def _empreinte_historique() -> tuple:
    """Taille et date de l'historique de cotes — assez pour détecter qu'il a
    grandi, sans le relire ni le parser."""
    from src.agents.quant.betting_engine.clv.store import JsonlOddsHistoryStore
    try:
        chemin = JsonlOddsHistoryStore().path
        etat = chemin.stat()
        return (etat.st_size, int(etat.st_mtime))
    except Exception:   # noqa: BLE001 — pas d'historique : rien à invalider
        return ()


@functools.lru_cache(maxsize=1)
def _seuil_clv() -> int | None:
    """Rencontres indépendantes exigées par la politique de maturité."""
    from src.agents.quant.betting_engine.maturity import load_maturity_policy
    try:
        return load_maturity_policy().criteria["min_clv_events"]
    except Exception:   # noqa: BLE001
        return None


@functools.lru_cache(maxsize=32)
def _readiness_memorisee(sports: tuple[str, ...],
                         _empreinte: tuple = ()) -> tuple[ModelReadiness, ...]:
    from src.agents.quant.betting_engine.maturity import Verdict
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS

    sorties: list[ModelReadiness] = []
    for sport in sorted(set(sports)):
        for cle in _READINESS_KEYS.get(sport, ()):
            evaluateur = _ASSESSORS.get(cle)
            if evaluateur is None:
                continue
            try:
                # Les paires RÉELLEMENT collectées pour ce modèle. Sans elles,
                # l'historique se remplirait sans que le critère bouge jamais.
                from src.agents.quant.betting_engine.readiness_cli import (
                    observations_collectees,
                )
                evaluation = evaluateur(observations_collectees(cle))
            except Exception:   # noqa: BLE001 — l'observabilité ne casse jamais un run
                continue
            decision = evaluation.decision
            observations = getattr(evaluation, "observations", None)
            requis = [c for c in decision.criteria if c.required]
            sorties.append(ModelReadiness(
                model_name=decision.model_name,
                model_version=decision.model_version,
                sport=sport,
                status=decision.status,
                passed=tuple(c.name for c in requis if c.verdict is Verdict.PASS),
                failed=tuple(c.name for c in requis if c.verdict is Verdict.FAIL),
                not_measurable=tuple(c.name for c in requis
                                     if c.verdict is Verdict.NOT_MEASURABLE),
                monitoring=tuple((c.name, c.verdict.value)
                                 for c in decision.criteria if not c.required),
                blockers=tuple(c.name for c in requis if c.verdict is not Verdict.PASS),
                clv_events=getattr(observations, "clv_n_events", None),
                clv_required=_seuil_clv(),
                criteres=tuple((c.name, c.verdict.value, c.detail) for c in requis),
            ))
    return tuple(sorties)
