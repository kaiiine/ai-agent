"""Orchestrateur sport LIVE — pour UN événement : scan Winamax -> BettingDecision.

Enchaîne, à partir d'un `RawBookmakerEvent` déjà scanné :
    résolution identité -> canonicalisation marché -> features live -> prédiction
    -> décision.

Invariants durs :
- **Jamais de `MarketPrediction` fabriquée** : `predict()` n'est appelé que si la
  readiness est suffisante ; `evaluate_selection` n'est appelé qu'avec de vraies
  probabilités. Sinon, refus explicite auditable (`LiveEvaluationResult`).
- **`decision_time` injecté**, capturé une seule fois par l'appelant : jamais de
  `now()` dans cette couche. `features.as_of == decision_time`,
  `predict(point_in_time=decision_time)`. Jamais `scheduled_at` comme cutoff.
- Sortie toujours `ABSTAIN` (modèle EXPERIMENTAL, BE-FR-011 actif). Ne touche
  jamais `calibration/` ni le statut du modèle. Pas de boucle catalogue.
"""

from __future__ import annotations

import functools

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable

from src.agents.quant.gateway.registries.provider_coverage_registry import usable_providers

from .bookmakers.bookmaker_registry import BookmakerEventResolver
from .bookmakers.canonical_binding import build_canonical_event
from .bookmakers.market_canonicalizer import (
    MarketCanonicalizationStatus,
    canonicalize_market,
    resolve_participant_roles,
)
from .bookmakers.participant_role_resolver import ParticipantRoleResolver
from .bookmakers.protocol import RawBookmakerEvent
from .core.canonical_event import CanonicalEvent
from .core.feature_set import EventFeatureSet
from .core.market_model import FOOTBALL_1X2, DataReadiness, MarketPrediction, MarketSchema
from .sports.registry import SPORT_MODULES, SportModule
from .value_engine import BettingDecision, evaluate_selection

# Tolérance de staleness LIVE : désormais versionnée dans
# configs/gateway/freshness_policy.json (plus un placeholder codé en dur). Valeur
# inchangée (48h) mais inspectable ; reste un seuil live non backtestable, à
# recalibrer une fois la fraîcheur mesurée exposée bout en bout (dette structurée).
def _default_staleness_tolerance() -> timedelta:
    from src.agents.quant.gateway.core.freshness_policy import default_freshness_policy
    return default_freshness_policy().live_staleness_tolerance

_FRESHNESS_UNAVAILABLE = (
    "freshness_unavailable: la gateway n'expose pas la fraîcheur via son API "
    "publique ; staleness non vérifiée (live uniquement, non backtestable)"
)
_FRESHNESS_DEGRADED = (
    "freshness_degraded: la gateway expose la fraîcheur mais la donnée servie n'a "
    "pas d'horodatage fiable (repli sur fetched_at) ; la mesure est propagée avec "
    "cette réserve — aucune fraîcheur favorable inventée"
)
def _model_schema(module: SportModule) -> MarketSchema:
    """Schéma de marché DÉCLARÉ par le modèle du sport (défaut football 1X2). C'est
    lui — jamais un `if sport ==` — qui porte le nombre d'issues (2-way vs 3-way)."""
    return getattr(module.model, "schema", FOOTBALL_1X2)


def _find_market(raw_event: RawBookmakerEvent, schema: MarketSchema):
    """Premier marché correspondant au (market_type, template) du schéma — générique."""
    for market in raw_event.markets:
        if market.market_type.value == schema.market_type and market.template == schema.template:
            return market
    return None


class LiveEvaluationStatus(str, Enum):
    EVALUATED = "EVALUATED"
    EVENT_NOT_RESOLVED = "EVENT_NOT_RESOLVED"
    # Identité de COMPÉTITION non résolue — cause distincte d'un participant inconnu.
    # Les deux donnaient « EVENT_NOT_RESOLVED », si bien qu'un tid bookmaker non
    # mappé se présentait comme une équipe introuvable : le diagnostic envoyait
    # corriger l'orthographe d'un nom d'équipe parfaitement correct.
    COMPETITION_NOT_RESOLVED = "COMPETITION_NOT_RESOLVED"
    MARKET_CANONICALIZATION_FAILED = "MARKET_CANONICALIZATION_FAILED"
    SPORT_NOT_SUPPORTED = "SPORT_NOT_SUPPORTED"
    COMPETITION_NOT_COVERED = "COMPETITION_NOT_COVERED"
    GATEWAY_UNAVAILABLE = "GATEWAY_UNAVAILABLE"
    DATA_TOO_STALE = "DATA_TOO_STALE"
    INSUFFICIENT_FEATURES = "INSUFFICIENT_FEATURES"


@dataclass(frozen=True)
class LiveEvaluationResult:
    status: LiveEvaluationStatus
    reason: str
    decision_time: datetime
    bookmaker_event_id: str
    canonical_event: CanonicalEvent | None = None
    feature_set: EventFeatureSet | None = None
    predictions: dict[str, MarketPrediction] = field(default_factory=dict)   # {} sauf EVALUATED
    decisions: tuple[BettingDecision, ...] = ()                              # () sauf EVALUATED
    warnings: list[str] = field(default_factory=list)
    error_context: dict = field(default_factory=dict)
    # Fraîcheur MESURÉE par la Gateway (0..1), propagée à l'aval (adaptateur/Advisor).
    # None = non mesurable (jamais fabriquée). Distincte du gate DATA_TOO_STALE.
    freshness_score: float | None = None

    @property
    def is_evaluated(self) -> bool:
        return self.status is LiveEvaluationStatus.EVALUATED

    @property
    def has_actionable_evaluation(self) -> bool:
        """Une VRAIE `MarketPrediction` a été calculée — l'ABSTAIN éventuel est
        alors un cap modèle (MODEL_NOT_SUPPORTED), pas un refus AVANT prédiction.

        Source UNIQUE de la classification « exploitable » : le CLI en dérive son
        code de sortie via cette propriété, jamais via une liste de statuts
        reconstruite à la main. Tout nouveau statut d'échec ajouté au contrat est
        automatiquement non-exploitable (≠ EVALUATED), sans modifier le CLI."""
        return self.status is LiveEvaluationStatus.EVALUATED


def _season_of(dt: datetime) -> str:
    return str(dt.year if dt.month >= 7 else dt.year - 1)


@functools.lru_cache(maxsize=1)
def _referentiel_multisport():
    """Le référentiel des SEPT sports, construit une fois.

    Import tardif : `sports.registry` charge les sept modules sportifs, et ce
    module est lui-même dans leur chaîne d'import.
    """
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver

    from .sports.registry import all_known_entities

    return IdentityResolver(all_known_entities())


def _appeler_freshness(sports_gateway, competition_id: str, season: str):
    """Interroge la fraîcheur en fournissant le référentiel complet.

    Une gateway de test peut exposer une signature réduite — le `hasattr` en
    amont accepte tout objet portant `data_freshness`. On retombe donc sur
    l'appel simple plutôt que d'imposer un paramètre à des doublures qui n'ont
    aucune raison de le connaître.
    """
    try:
        return sports_gateway.data_freshness(
            competition_id, season, resolver=_referentiel_multisport())
    except TypeError:
        return sports_gateway.data_freshness(competition_id, season)


def evaluate_live_event(
    raw_event: RawBookmakerEvent,
    *,
    decision_time: datetime,
    event_resolver: BookmakerEventResolver,
    sports_gateway,
    role_resolver: ParticipantRoleResolver | None = None,
    sport_modules: dict[str, SportModule] = SPORT_MODULES,
    coverage_check: Callable[..., list[str]] = usable_providers,
    freshness_probe: Callable[[], timedelta | None] | None = None,
    staleness_tolerance: timedelta | None = None,
) -> LiveEvaluationResult:
    warnings: list[str] = []
    if staleness_tolerance is None:                     # défaut = politique versionnée (jamais un hardcode)
        staleness_tolerance = _default_staleness_tolerance()

    def result(status, reason, **kw) -> LiveEvaluationResult:
        return LiveEvaluationResult(
            status=status, reason=reason, decision_time=decision_time,
            bookmaker_event_id=raw_event.bookmaker_event_id, warnings=warnings, **kw,
        )

    # 1) Dispatch sport (aucun "football" en dur ici).
    module = sport_modules.get(raw_event.sport)
    if module is None:
        return result(LiveEvaluationStatus.SPORT_NOT_SUPPORTED,
                      f"sport non enregistré : {raw_event.sport}")

    # 2) Résolution identité — participants et compétition sont deux causes SÉPARÉES.
    #    L'evidence porte déjà le sujet en échec ("competition" vs "slot_N") ; la
    #    fondre dans un statut unique perdait l'information au moment précis où elle
    #    sert au diagnostic.
    mapping = event_resolver.resolve_event(raw_event)
    if not mapping.is_usable:
        failed = [e for e in mapping.evidence if e.status != "RESOLVED"]
        if failed and all(e.subject == "competition" for e in failed):
            return result(
                LiveEvaluationStatus.COMPETITION_NOT_RESOLVED,
                f"compétition bookmaker non mappée (tid={raw_event.raw_tournament_id!r}) — "
                f"les participants, eux, sont résolus")
        return result(LiveEvaluationStatus.EVENT_NOT_RESOLVED,
                      f"identity={mapping.identity_status} eligibility={mapping.eligibility_status}"
                      + (f" ; sujets en échec : {', '.join(e.subject for e in failed)}" if failed else ""))

    # 3) Canonicalisation ATOMIQUE du marché — piloté par le SCHÉMA du sport (2/3-way).
    schema = _model_schema(module)
    market = _find_market(raw_event, schema)
    if market is None:
        return result(LiveEvaluationStatus.MARKET_CANONICALIZATION_FAILED,
                      f"aucun marché {schema.market_type}/{schema.template} dans l'événement")
    role_resolution = resolve_participant_roles(raw_event, role_resolver)
    canon = canonicalize_market(raw_event, market, mapping, role_resolution, schema=schema)
    if canon.status is not MarketCanonicalizationStatus.OK:
        return result(LiveEvaluationStatus.MARKET_CANONICALIZATION_FAILED,
                      f"{canon.status.value}: {canon.reason}")

    event = build_canonical_event(raw_event, mapping, role_resolver)   # is_usable déjà vrai

    # 4) Pré-check couverture (distingue non-couvert de forme mince).
    season = _season_of(decision_time)
    if not coverage_check(mapping.competition_id, season, "RESULTS"):
        return result(LiveEvaluationStatus.COMPETITION_NOT_COVERED,
                      f"aucun provider utilisable pour {mapping.competition_id} ({season})",
                      canonical_event=event)

    # 5) Features live — as_of = decision_time. Toute exception inattendue = frontière.
    try:
        features = module.build_feature_set(event, gateway=sports_gateway, as_of=decision_time)
    except Exception as exc:   # noqa: BLE001 — frontière : on garde type + contexte
        return result(LiveEvaluationStatus.GATEWAY_UNAVAILABLE,
                      f"exception gateway : {type(exc).__name__}",
                      canonical_event=event,
                      error_context={"type": type(exc).__name__, "repr": repr(exc)})

    # 6) Fraîcheur : seam explicite, jamais "frais" supposé en silence.
    #    Priorité : sonde injectée (test, âge seul) > capacité Gateway (production,
    #    "Gateway calcule -> BE lit" : âge ET score mesuré) > aucune capacité (warning).
    #    Le score mesuré (0..1) est PROPAGÉ (result.freshness_score) pour l'aval
    #    (adaptateur/Advisor) ; None quand non mesurable, jamais fabriqué.
    freshness_notes: list[str] = []
    measured_freshness: float | None = None
    if freshness_probe is not None:
        staleness = freshness_probe()
        if staleness is None:
            freshness_notes.append(_FRESHNESS_DEGRADED)
        elif staleness > staleness_tolerance:
            return result(LiveEvaluationStatus.DATA_TOO_STALE,
                          f"données trop anciennes ({staleness} > {staleness_tolerance})",
                          canonical_event=event, feature_set=features)
    elif hasattr(sports_gateway, "data_freshness"):
        # Le référentiel des SEPT sports est passé explicitement : celui de la
        # Gateway ne contient que des équipes de football, si bien qu'un provider
        # répondant parfaitement pour le hockey voyait chacune de ses rencontres
        # écartée faute d'identité, et rendait une enveloppe vide. Le manque se
        # lisait « aucune donnée » là où c'était le référentiel qui manquait.
        info = _appeler_freshness(sports_gateway, mapping.competition_id, season)
        if info is None or info.effective_time is None:
            # Aucun horodatage exploitable : NON MESURABLE, et rien de fabriqué.
            freshness_notes.append(_FRESHNESS_DEGRADED)
        else:
            # `degraded` dit que la BASE est plus faible (`fetched_at` au lieu de
            # `published_time`), pas que la mesure est absente. Les confondre
            # transformait une fraîcheur mesurée à 0,0001 — donc une donnée
            # manifestement périmée — en « inconnue », c'est-à-dire en un doute
            # plus favorable que la mesure elle-même.
            if info.degraded:
                freshness_notes.append(_FRESHNESS_DEGRADED)
            measured_freshness = info.freshness_score        # MESURÉ par la Gateway (0..1)
            staleness = decision_time - info.effective_time
            if staleness > staleness_tolerance:
                return result(LiveEvaluationStatus.DATA_TOO_STALE,
                              f"données trop anciennes ({staleness} > {staleness_tolerance})",
                              canonical_event=event, feature_set=features)
    else:
        freshness_notes.append(_FRESHNESS_UNAVAILABLE)
    warnings.extend(freshness_notes)

    # 7) Readiness — jamais de prédiction fabriquée.
    if module.model.assess_data_readiness(event, features) == DataReadiness.INSUFFICIENT_DATA:
        return result(LiveEvaluationStatus.INSUFFICIENT_FEATURES,
                      "données insuffisantes pour ce marché (readiness INSUFFICIENT_DATA)",
                      canonical_event=event, feature_set=features)

    # 8) Prédiction RÉELLE (point_in_time = decision_time).
    predictions = module.model.predict_selections(event, features, point_in_time=decision_time)

    # Les notes de fraîcheur (indispo / dégradée) doivent vivre AUSSI dans
    # l'explication de la prédiction, pas seulement dans le résultat d'orchestration.
    if freshness_notes:
        predictions = {
            sel: replace(pred, explanation=replace(
                pred.explanation, warnings=list(pred.explanation.warnings) + freshness_notes))
            for sel, pred in predictions.items()
        }

    # 9) Décision par sélection (toujours ABSTAIN, BE-FR-011). Issues du SCHÉMA (2/3-way).
    expected = frozenset(schema.selections)
    decisions = tuple(
        evaluate_selection(predictions[sel], canon.snapshots, expected_selections=expected)
        for sel in schema.selections
    )

    return result(LiveEvaluationStatus.EVALUATED, "ok",
                  canonical_event=event, feature_set=features,
                  predictions=predictions, decisions=decisions,
                  freshness_score=measured_freshness)
