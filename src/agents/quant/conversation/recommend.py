"""Orchestration conversationnelle -> Advisor. Le SEUL chemin de recommandation.

    UserBettingConstraints
      -> TimeWindow (filtrage AVANT évaluation)
      -> RecommendationRequest
      -> scan Winamax -> Betting Engine -> Adapter -> Advisor
      -> RecommendationResponse + BettingResponseEvidence

Aucun calcul ici : ni probabilité, ni EV, ni cote implicite, ni mise, ni proba
jointe. Ce module compose et mesure ; toute grandeur affichée vient d'un objet du
domaine.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Sequence

from .constraints import UserBettingConstraints
from .evidence import BettingResponseEvidence
from .observability import (
    RunObservability,
    ScanTelemetry,
    build_traces,
    collect_readiness,
)
from .window import TimeWindow

# Statuts de sortie du pont conversationnel (jamais un texte libre).
CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
FILTER_UNRESOLVED = "FILTER_UNRESOLVED"
EMPTY_WINDOW = "EMPTY_WINDOW"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class RecommendationRun:
    """Résultat d'un tour. `response` n'existe que si `status == COMPLETED`."""

    status: str
    constraints: UserBettingConstraints
    response: Any = None
    evidence: BettingResponseEvidence | None = None
    detail: str = ""
    available: tuple[str, ...] = ()
    #: Vue additive du run. Aucune décision n'en dépend : la retirer ne changerait
    #: pas une probabilité, un statut ni une mise.
    observability: RunObservability | None = None


# ── Résolution des filtres : jamais d'élargissement silencieux ────────────────
def resolve_sport_filter(
    tokens: frozenset[str] | None, known: Sequence[str],
) -> tuple[frozenset[str] | None, tuple[str, ...]]:
    """Traduit les sports demandés en sports enregistrés. Un jeton inconnu est
    RENDU, jamais ignoré : ignorer « padel » reviendrait à scanner les sept
    sports pour une demande qui en visait un seul."""
    if tokens is None:
        return None, ()
    connus = {s.lower(): s for s in known}
    alias = {"foot": "football", "soccer": "football", "basket": "basketball",
             "nfl": "american_football", "football americain": "american_football",
             "hockey sur glace": "hockey", "volley": "volleyball", "baseball": "baseball"}
    retenus, inconnus = set(), []
    for token in tokens:
        cle = alias.get(token, token)
        if cle in connus:
            retenus.add(connus[cle])
        else:
            inconnus.append(token)
    return frozenset(retenus), tuple(inconnus)


def resolve_competition_filter(
    tokens: frozenset[str] | None, available: Sequence[str],
) -> tuple[frozenset[str] | None, tuple[str, ...]]:
    """Traduit « ATP » en `competition:tennis:atp:tour`.

    Le référentiel de compétitions ne couvre que le football ; la seule liste
    fiable est donc celle des compétitions RÉELLEMENT présentes dans le scan du
    tour. Un jeton est reconnu s'il correspond à un SEGMENT de l'identifiant
    canonique — « atp » ne peut donc pas attraper la WTA, et « ligue1 » ne peut
    pas attraper la Ligue 2.
    """
    if tokens is None:
        return None, ()
    retenus, inconnus = set(), []
    for token in tokens:
        compact = token.replace(" ", "").replace("-", "_")
        trouve = {
            comp for comp in available
            if compact in {seg.lower().replace(" ", "").replace("-", "_")
                           for seg in comp.split(":")}
        }
        if trouve:
            retenus |= trouve
        else:
            inconnus.append(token)
    return frozenset(retenus), tuple(inconnus)


# ── Dépendances réelles (injectables pour les tests hermétiques) ──────────────
def _default_scan(window: TimeWindow, sports: Sequence[str], decision_time: datetime):
    """Scan multisport RÉEL, filtré par la fenêtre AVANT toute évaluation.

    Filtrer après coup laisserait des matchs hors fenêtre atteindre le modèle et,
    de là, le classement : « hors fenêtre mais intéressant » est exactement ce
    qu'il ne faut jamais produire.

    Appelle `evaluate_live_batch` puis `adapt_live_batch` au lieu du raccourci
    `load_and_adapt`, qui est exactement leur composition. La différence est
    entièrement observationnelle : le batch de domaine porte UN résultat par
    rencontre, avec son `RawBookmakerEvent` — donc son sport, sa compétition et
    son horaire. L'`AdaptedBatch`, lui, réduit un refus à des identifiants, et
    aucun refus n'y est plus attribuable à un sport.
    """
    import functools

    from ..advisor.input_adapter.betting_engine_adapter import adapt_live_batch
    from ..betting_engine.bookmakers.winamax.catalogue import multisport_events
    from ..betting_engine.bookmakers.winamax.connector import WinamaxConnector
    from ..betting_engine.live_batch import evaluate_live_batch
    from ..betting_engine.live_coverage import evaluation_coverage_check
    from ..betting_engine.live_evaluation import evaluate_live_event
    from ..betting_engine.sports.registry import build_event_resolver
    from ..gateway import gateway as sports_gateway

    connector = WinamaxConnector()
    compte: Counter = Counter()
    competitions: dict[str, set[str]] = {}

    def catalogue(conn):
        events = multisport_events(conn, list(sports))
        compte["scannes"] = len(events)
        for event in events:
            competitions.setdefault(event.sport, set()).add(
                event.competition or "sans libellé")
        retenus = [e for e in events if window.contains(e.start_time)]
        compte["dans_fenetre"] = len(retenus)
        return retenus

    batch = evaluate_live_batch(
        connector, sports_gateway=sports_gateway,
        event_resolver=build_event_resolver(), catalogue=catalogue,
        evaluate=functools.partial(evaluate_live_event,
                                   coverage_check=evaluation_coverage_check),
        now_fn=lambda: decision_time)

    # Le catalogue de sports est DÉCOUVERT, jamais une whitelist : c'est lui qui
    # distingue « Winamax n'expose pas ce sport » de « nous n'avons pas de modèle
    # pour ce sport ». Son échec ne doit pas coûter le run — la carte reste vide.
    try:
        catalog_sports = connector.discover_sports()
    except Exception:   # noqa: BLE001
        catalog_sports = {}

    telemetrie = ScanTelemetry(
        catalog_sports=catalog_sports,
        scanned_sports=tuple(sports),
        catalog_events_total=compte["scannes"],
        events_outside_window=compte["scannes"] - compte["dans_fenetre"],
        events_inside_window=compte["dans_fenetre"],
        catalog_competitions={s: tuple(sorted(c)) for s, c in sorted(competitions.items())},
    )
    return adapt_live_batch(batch), telemetrie, build_traces(batch.results)


def _default_configs() -> dict:
    from ..advisor.cli import _load_configs
    return _load_configs()


def _default_audit(request, batch, result, cfg) -> None:
    from ..advisor.cli import _persist_audit
    _persist_audit(request, batch, result, cfg, None)


# ── Le tour ───────────────────────────────────────────────────────────────────
def run_recommendation(
    constraints: UserBettingConstraints,
    *,
    now: datetime,
    scan: Callable = _default_scan,
    configs: Callable[[], dict] = _default_configs,
    persist_audit: Callable | None = _default_audit,
    request_id: str | None = None,
    readiness: Callable[[Sequence[str]], tuple] | None = None,
) -> RecommendationRun:
    from ..advisor.domain.enums import MaturityPolicy, RiskProfile
    from ..advisor.domain.requests import RecommendationRequest
    from ..advisor.pipeline import run_pipeline
    from ..betting_engine.sports.registry import SPORT_MODULES

    if constraints.missing():
        return RecommendationRun(
            CLARIFICATION_REQUIRED, constraints,
            detail="bankroll requise : aucun dimensionnement n'est possible sans elle")

    window = constraints.time_window
    if window is None:
        raise ValueError("fenêtre temporelle non résolue : appeler resolve_window en amont")
    if window.is_empty:
        return RecommendationRun(
            EMPTY_WINDOW, constraints,
            detail=f"fenêtre demandée entièrement passée : {window.describe()}")

    sports_scope, sports_inconnus = resolve_sport_filter(
        constraints.resolved_scope("sports"), sorted(SPORT_MODULES))
    if sports_inconnus:
        return RecommendationRun(
            FILTER_UNRESOLVED, constraints,
            detail=f"sport(s) non couvert(s) : {', '.join(sorted(sports_inconnus))}",
            available=tuple(sorted(SPORT_MODULES)))

    sports = sorted(sports_scope) if sports_scope else sorted(SPORT_MODULES)
    scan_started_at = now

    try:
        batch, telemetrie, traces = scan(window, sports, now)
    except Exception as exc:   # noqa: BLE001 — scan total impossible
        return RecommendationRun(
            DATA_UNAVAILABLE, constraints,
            detail=f"scan indisponible : {type(exc).__name__}: {exc}")

    scan_completed_at = datetime.now(now.tzinfo)

    disponibles = sorted({e.competition_id for e in batch.evaluations})
    competitions_scope, comp_inconnues = resolve_competition_filter(
        constraints.resolved_scope("competitions"), disponibles)
    if comp_inconnues:
        return RecommendationRun(
            FILTER_UNRESOLVED, constraints,
            detail=("compétition(s) absente(s) du scan : "
                    f"{', '.join(sorted(comp_inconnues))}"),
            available=tuple(disponibles))

    request = RecommendationRequest(
        request_id=request_id or f"req:{uuid.uuid4().hex}",
        decision_time=now,
        bankroll=constraints.bankroll,
        currency="EUR",
        allowed_sports=sports_scope,
        allowed_competitions=competitions_scope,
        allowed_bookmakers=None,
        allowed_market_types=constraints.resolved_scope("markets"),
        target_total_odds=None,
        max_total_stake=None,
        max_selections=1,
        max_portfolios=1,
        allow_singles=constraints.allow_singles,
        allow_combos=constraints.allow_combos,
        max_combo_legs=2,
        risk_profile=RiskProfile[constraints.risk_profile.upper()],
        # EXPERIMENTAL entre en REVUE, jamais en mise : `maturity_decision` rend
        # REVIEW_ONLY, et un REVIEW_ONLY ne produit aucun portefeuille. Refuser
        # d'évaluer tout court ne dirait rien à l'utilisateur ; l'évaluer sans
        # pouvoir le miser dit exactement la vérité de l'état du modèle.
        maturity_policy=MaturityPolicy.INCLUDE_EXPERIMENTAL_FOR_REVIEW,
        ranking_profile="balanced_v1",
        excluded_event_ids=frozenset(),
        excluded_participant_ids=frozenset(),
        excluded_market_types=frozenset(),
    )

    cfg = configs()
    try:
        result = run_pipeline(batch, request, **cfg)
    except Exception as exc:   # noqa: BLE001
        return RecommendationRun(
            TECHNICAL_FAILURE, constraints,
            detail=f"échec du pipeline : {type(exc).__name__}: {exc}")

    if persist_audit is not None:
        try:
            persist_audit(request, batch, result, cfg)
        except Exception:   # noqa: BLE001 — l'audit ne doit jamais casser la réponse
            pass

    response = result.recommendation

    # `PipelineRunResult.trace` était produit puis jeté. Il porte l'évaluation de
    # politique de CHAQUE candidat — y compris ceux qui ne ressortent nulle part
    # dans la réponse, et dont on ne pouvait donc pas dire pourquoi ils sont
    # absents.
    observabilite = RunObservability(
        telemetry=telemetrie,
        traces=traces,
        model_capable_sports=tuple(sorted(SPORT_MODULES)),
        policy_evaluations=tuple(result.trace.policy_evaluations),
        readiness=(readiness or (lambda _: ()))(
            tuple(sorted({t.sport for t in traces if t.evaluated}))),
        adapted_by_key={(e.event_id, e.market_id, e.selection): e
                        for e in batch.evaluations},
    )

    evidence = BettingResponseEvidence(
        request_id=request.request_id,
        run_id=f"run:{uuid.uuid4().hex[:12]}",
        scan_started_at=scan_started_at,
        scan_completed_at=scan_completed_at,
        window_start=window.start,
        window_end=window.end,
        sports_scanned=tuple(sports),
        event_ids=tuple(sorted({e.event_id for e in batch.evaluations})),
        recommendation_outcome=response.outcome.value,
        audit_id=response.audit_id,
        events_scanned=telemetrie.catalog_events_total,
        events_in_window=telemetrie.events_inside_window,
        # RENCONTRES, pas sélections : `len(batch.evaluations)` comptait deux ou
        # trois lignes par match, et ne se raccordait donc à aucun autre compteur.
        events_evaluated=observabilite.events_evaluated,
        reason_counts=dict(response.rejection_summary),
    )
    return RecommendationRun(COMPLETED, constraints, response=response, evidence=evidence,
                             observability=observabilite)


def bankroll_decimal(value: float | str | None) -> Decimal | None:
    """Bankroll en Decimal — jamais un float. `Decimal(0.1)` vaut
    0.1000000000000000055511151231257827, et cette poussière se propage jusqu'à
    la mise affichée."""
    if value is None:
        return None
    return Decimal(str(value))
