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
    from ..betting_engine.bookmakers.bookmaker_registry import MemoizingEventResolver
    from ..betting_engine.bookmakers.winamax.catalogue import fetch_all_markets, multisport_scan
    from ..betting_engine.bookmakers.winamax.connector import WinamaxConnector
    from ..betting_engine.live_batch import evaluate_live_batch
    from ..betting_engine.live_coverage import evaluation_coverage_check
    from ..betting_engine.live_evaluation import evaluate_live_event
    from ..betting_engine.sports.registry import build_event_resolver
    from ..gateway import gateway as sports_gateway

    connector = WinamaxConnector()
    # LE MÊME résolveur que l'évaluation, par construction : décider quelles pages
    # valent un appel avec un résolveur différent de celui qui évalue ferait
    # écarter des rencontres parfaitement évaluables, sans que rien ne le signale.
    # Mémorisé POUR CE RUN : chaque rencontre est désormais résolue deux fois —
    # une fois pour décider si sa page de marchés vaut un appel réseau, une fois à
    # l'évaluation. Mesuré : 502 résolutions pour 261 rencontres, 13,2 s sur 40.
    resolveur = MemoizingEventResolver(build_event_resolver())
    compte: Counter = Counter()
    competitions: dict[str, set[str]] = {}
    vus_par_sport: dict[str, int] = {}
    pannes: dict[str, str] = {}
    pannes_marches: dict[str, str] = {}

    def catalogue(conn):
        # Un sport dont la source tombe ne fait plus tomber les autres : sa panne
        # devient un statut porté jusqu'au rendu. Si AUCUN sport n'a répondu, on
        # relaie l'échec — il n'y a alors pas de scan partiel, il n'y a pas de scan.
        resultat = multisport_scan(conn, list(sports))
        pannes.update(resultat.failures)
        if resultat.total_failure:
            raise RuntimeError(
                "aucun sport n'a pu être interrogé — "
                + " ; ".join(f"{s} ({p})" for s, p in sorted(resultat.failures.items())))
        events = list(resultat.events)
        compte["scannes"] = len(events)
        for event in events:
            competitions.setdefault(event.sport, set()).add(
                event.competition or "sans libellé")
            # Dénominateur de la couverture : le CATALOGUE, pas ce qui a survécu
            # jusqu'à l'évaluation.
            vus_par_sport[event.sport] = vus_par_sport.get(event.sport, 0) + 1
        retenus = [e for e in events if window.contains(e.start_time)]
        compte["dans_fenetre"] = len(retenus)

        # TOUS LES MARCHÉS, et seulement pour ce qui sera réellement évalué. La
        # page catalogue n'en sert qu'un par rencontre : sans cette étape, le
        # produit continuerait de ne voir que « qui gagne » et de le présenter
        # comme l'offre du bookmaker.
        #
        # DEUX FILTRES, ET AUCUN N'EST COSMÉTIQUE. La fenêtre d'abord : payer une
        # page pour un match de la semaine prochaine serait un appel réseau pour
        # une rencontre qu'on n'évaluera pas. L'identité ensuite : une rencontre
        # que le résolveur ne sait pas nommer n'atteindra aucun modèle, quels que
        # soient ses deux cents marchés. Ces pages-là sont exactement celles qui
        # ont valu un 403 au run précédent — 83 % des marchés téléchargés, zéro
        # marché priceable en plus.
        enrichissement = fetch_all_markets(
            conn, retenus,
            should_fetch=lambda e: resolveur.resolve_event(e).is_usable)
        pannes_marches.update(enrichissement.failures)
        compte["marches_avant"] = enrichissement.markets_before
        compte["marches_apres"] = enrichissement.markets_after
        compte["evenements_enrichis"] = enrichissement.enriched
        compte["evenements_sans_page"] = enrichissement.skipped
        compte["marches_declares_non_lus"] = enrichissement.skipped_declared_markets
        return list(enrichissement.events)

    batch = evaluate_live_batch(
        connector, sports_gateway=sports_gateway,
        event_resolver=resolveur, catalogue=catalogue,
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
        events_seen_by_sport=dict(sorted(vus_par_sport.items())),
        scan_failures=dict(sorted(pannes.items())),
        markets_from_catalog=compte["marches_avant"],
        markets_after_event_pages=compte["marches_apres"],
        events_market_enriched=compte["evenements_enrichis"],
        events_without_market_page=compte["evenements_sans_page"],
        declared_markets_not_fetched=compte["marches_declares_non_lus"],
        market_fetch_failures=dict(sorted(pannes_marches.items())),
        market_funnel=agreger_entonnoirs(batch.results),
    )
    return adapt_live_batch(batch), telemetrie, build_traces(batch.results)


#: Motif d'exclusion d'un événement dont AUCUN marché n'a atteint l'étape prix.
#: Préfixé par son statut d'évaluation : « aucun modèle » et « compétition non
#: couverte » ne se réparent pas de la même façon.
_EVENEMENT_NON_PRICE = "EVENT_NOT_PRICED"


def agreger_entonnoirs(resultats):
    """Les entonnoirs marché de tous les événements, en un seul.

    LE DÉNOMINATEUR EST LE CATALOGUE, PAS LES SURVIVANTS. Un événement qui n'a
    jamais atteint l'étape marché — sport sans modèle dérivé, compétition non
    couverte, identité non résolue — a quand même des marchés, et les omettre
    ferait porter tous les taux sur les seules rencontres qui ont réussi.
    Mesuré : 1 164 marchés comptés contre 32 777 réellement rapportés, soit un
    entonnoir qui décrivait 4 % du catalogue en se présentant comme complet.

    Additionne des compteurs, jamais des taux : la moyenne de deux pourcentages
    calculés sur des dénominateurs différents ne veut rien dire.
    """
    from ..betting_engine.markets.event_pricing import MarketFunnel

    total = MarketFunnel()
    for raw_event, resultat in resultats:
        entonnoir = getattr(resultat, "market_funnel", None)
        if entonnoir is None:
            # Ses marchés existent : ils sont VUS, et écartés sous le motif de
            # l'événement lui-même.
            total.events_seen += 1
            marches = len(getattr(raw_event, "markets", ()) or ())
            total.markets_observed += marches
            statut = getattr(getattr(resultat, "status", None), "value", "UNKNOWN")
            total.exclusions[f"{_EVENEMENT_NON_PRICE}:{statut}"] += marches
            continue
        for champ in ("events_seen", "events_priced", "markets_observed",
                      "markets_canonicalized", "markets_capability_available",
                      "markets_priced", "markets_with_probability_low",
                      "markets_freshness_measurable", "selections_priced"):
            setattr(total, champ, getattr(total, champ) + getattr(entonnoir, champ))
        total.exclusions.update(entonnoir.exclusions)
    return total


def _construire_review(batch, freshness_at, policy_evaluations=()):
    """Le classement multi-marché du run, ou rien s'il ne peut pas être construit.

    Une panne du classement ne doit pas coûter la recommandation : celle-ci est
    déjà calculée quand on arrive ici, et l'échanger contre une vue additive
    serait un mauvais marché. L'échec reste visible — `review` vaut `None`, et
    `None` n'est pas un classement vide.
    """
    try:
        from .market_review import construire_review
        return construire_review(batch, freshness_at=freshness_at,
                                 policy_evaluations=policy_evaluations)
    except Exception:   # noqa: BLE001 — une vue ne casse jamais un run
        return None


def _default_configs() -> dict:
    from ..advisor.cli import _load_configs
    return _load_configs()


def _default_audit(request, batch, result, cfg) -> None:
    from ..advisor.cli import _persist_audit
    _persist_audit(request, batch, result, cfg, None)


def _default_capture(evaluations, **kwargs) -> None:
    from ..betting_engine.outcomes.capture import capturer_predictions
    capturer_predictions(evaluations, **kwargs)


def _default_coverage(observability, *, response, evidence) -> None:
    """Mesure la couverture du run et l'archive. Injectée, donc neutralisable."""
    from ..betting_engine.catalog_coverage import JsonlCoverageStore, mesurer
    JsonlCoverageStore().append(
        mesurer(observability, response=response, evidence=evidence))


# ── Le tour ───────────────────────────────────────────────────────────────────
def run_recommendation(
    constraints: UserBettingConstraints,
    *,
    now: datetime,
    scan: Callable = _default_scan,
    configs: Callable[[], dict] = _default_configs,
    persist_audit: Callable | None = _default_audit,
    capture: Callable | None = _default_capture,
    coverage: Callable | None = _default_coverage,
    request_id: str | None = None,
    readiness: Callable[[Sequence[str]], tuple] | None = None,
    enrich: Callable[[Any, Sequence[str]], dict] | None = None,
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

    # Enrichissement Internet — APRÈS l'évaluation, et seulement pour la revue.
    # L'ordre n'est pas cosmétique : appelé avant, il pourrait influencer ce qui
    # est évalué ; appelé sur des BET, il coûterait du réseau pour des candidats
    # dont la décision est déjà prise.
    features = enrich(response, sports) if enrich is not None else {}

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
        internet_features=features,
        # Le classement multi-marché du run. Construit depuis le MÊME batch que
        # le pipeline money : les deux vues ne peuvent donc pas diverger sur un
        # nombre. Il ne décide rien — aucune mise n'en sort.
        #
        # L'âge des cotes se mesure à la FIN DE L'ACQUISITION, pas au
        # point-in-time du modèle : celui-ci précède le scan par construction, et
        # une cote lui est donc toujours postérieure.
        review=_construire_review(batch, scan_completed_at,
                                  result.trace.policy_evaluations),
    )

    # Capture des prédictions — la boucle de retour. Sans elle, le moteur annonce
    # des probabilités que rien ne vient jamais confronter au résultat.
    # INJECTÉE comme l'audit, et pour la même raison : appelée en dur, elle écrivait
    # dans le store RÉEL depuis la suite de tests. 515 prédictions synthétiques y
    # ont atterri avant que ça se voie — de quoi fausser toute calibration future.
    if capture is not None:
        try:
            capture(result.trace.policy_evaluations, decided_at=now,
                    adapted_for=observabilite.adapted_for, run_id=request.request_id)
        except Exception:   # noqa: BLE001 — la comptabilité ne casse jamais un scan
            pass

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
    # Couverture produit — mesurée sur CE run, jamais extrapolée. Après evidence,
    # qui porte la fenêtre et l'identifiant de run.
    if coverage is not None:
        try:
            coverage(observabilite, response=response, evidence=evidence)
        except Exception:   # noqa: BLE001 — une mesure ne casse jamais un scan
            pass

    return RecommendationRun(COMPLETED, constraints, response=response, evidence=evidence,
                             observability=observabilite)


def bankroll_decimal(value: float | str | None) -> Decimal | None:
    """Bankroll en Decimal — jamais un float. `Decimal(0.1)` vaut
    0.1000000000000000055511151231257827, et cette poussière se propage jusqu'à
    la mise affichée."""
    if value is None:
        return None
    return Decimal(str(value))
