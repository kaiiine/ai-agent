"""Schéma d'entrée VERSIONNÉ de l'adaptateur (PRD §9, ADV-NFR-011).

`AdaptedEvaluation` est la traduction FIDÈLE d'UNE sélection évaluée par le
Betting Engine : mêmes nombres (proba, cote, EV/edge/no-vig déjà calculés par le
moteur), typés `Decimal`, jamais recalculés. Les champs DÉRIVÉS (candidate_id,
fair_odds, edge_mean/low, exposure_keys) ne sont PAS ici : ils appartiennent au
Candidate Generator (Lot 3).

Le versionnage (`schema_version` sur `AdaptedBatch`) isole le ranking/portfolio
des évolutions de noms/formats du moteur : un changement de contrat source est
absorbé ici, ou rejeté explicitement (cf. `errors.IncompatibleSchemaError`).

IMPORTANT — pas de versioning de source aujourd'hui : le Betting Engine n'émet
AUCUN `contract_version`. La compatibilité réelle est garantie STRUCTURELLEMENT
par l'adaptateur (champs obligatoires présents, `canonical_event` requis,
prédiction/décision par sélection, maturités connues, erreur explicite sur toute
forme incompatible), pas par une négociation de version source. `EXPECTED_ENGINE_SCHEMA`
n'est donc PAS une valeur émise par le moteur : c'est l'étiquette du schéma de
sortie que CET adaptateur attend. Le jour où le moteur exposera un vrai
`contract_version`, l'adaptateur pourra le comparer à cette étiquette."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Version du contrat d'entrée Advisor produit par l'adaptateur.
INPUT_SCHEMA_VERSION = "1"

# Étiquette du SCHÉMA DE SORTIE MOTEUR ATTENDU par cet adaptateur — l'attente de
# l'adaptateur, PAS une valeur émise par le moteur (qui n'en émet aucune). Sert
# uniquement à un appelant qui veut épingler le schéma attendu et échouer
# bruyamment si l'adaptateur est réécrit vers un schéma qu'il ne cible pas. La
# compatibilité de la sortie réelle du moteur est validée STRUCTURELLEMENT.
EXPECTED_ENGINE_SCHEMA = "betting-engine.live.v1"

# Maturités de modèle connues (miroir de `DataReadiness`, SANS `DEPRECATED` que
# la source n'émet jamais — cf. Lot 0 §4.2). Une valeur hors de cet ensemble =
# contrat source inconnu -> rejet, jamais mappée en silence.
KNOWN_MATURITIES = frozenset(
    {"SUPPORTED", "EXPERIMENTAL", "INSUFFICIENT_DATA", "UNSUPPORTED"}
)


@dataclass(frozen=True)
class AdaptedExplanation:
    """Explication de prédiction PRÉSERVÉE telle quelle (aucun warning supprimé).
    Les valeurs de features sont des quantités de modèle (diagnostic), non
    monétaires : conservées en `float`, hors du périmètre Decimal (ADV-NFR-010)."""

    top_features: tuple[tuple[str, float], ...]
    missing_features: frozenset[str]
    confidence_drivers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class AdaptedEvaluation:
    """Une sélection évaluée, traduite fidèlement (une par home/draw/away)."""

    schema_version: str

    # Identité (propagée depuis CanonicalEvent / RawBookmakerEvent).
    event_id: str
    sport: str
    competition_id: str
    scheduled_at: datetime
    participant_ids: tuple[str, ...]

    # Instant d'OBSERVATION des cotes (côté bookmaker), = RawBookmakerEvent.fetched_at
    # (source de OddsSnapshot.observed_at). Distinct du decision_time Advisor :
    # c'est l'identité temporelle de l'OFFRE, pas de la requête (ADR-ADV-003).
    observed_at: datetime

    # Marché (market_id reconstruit via le builder canonique, jamais parallèle).
    bookmaker: str
    market_id: str
    market_type: str
    selection: str

    # Nombres du moteur -> Decimal, jamais recalculés.
    bookmaker_odds: Decimal
    fair_probability: Decimal
    probability_low: Decimal
    probability_high: Decimal
    uncertainty_status: str

    model_version: str
    model_maturity: str                 # = calibration_status, JAMAIS rehaussé
    data_quality: Decimal
    calibration_score: Decimal | None   # = model_reliability (None : calibration/ absent)
    freshness_score: Decimal | None     # None = FRESHNESS_UNKNOWN (Q1)
    liquidity_score: Decimal | None     # None : non exposé par la source

    # Métriques d'audit CALCULÉES PAR LE MOTEUR, seulement propagées (None si non évaluées).
    implied_probability_raw: Decimal | None
    no_vig_probability: Decimal | None
    edge: Decimal | None
    expected_value: Decimal | None

    is_boosted: bool
    decision: str                       # "ABSTAIN" en V1
    decision_reasons: tuple[str, ...]
    warnings: tuple[str, ...]           # union préservée résultat + explication
    explanation: AdaptedExplanation
    source_decision_id: str | None      # None tant qu'aucun id source réel (Q5)


@dataclass(frozen=True)
class SkippedEvaluation:
    """Événement scanné mais NON évaluable : tracé (id + statut + raison) pour
    que la couche recommandation produise NO_EVALUABLE_EVENTS / rejection_summary,
    sans fabriquer de candidat."""

    bookmaker_event_id: str
    event_id: str | None
    status: str
    reason: str


@dataclass(frozen=True)
class AdaptedBatch:
    """Sortie de l'adaptateur pour un `decision_time` : évaluations traduites +
    événements écartés (traçabilité), estampillé de la version de schéma."""

    schema_version: str
    decision_time: datetime
    evaluations: tuple[AdaptedEvaluation, ...]
    skipped: tuple[SkippedEvaluation, ...]

    def by_event(self) -> Mapping[str, tuple[AdaptedEvaluation, ...]]:
        out: dict[str, list[AdaptedEvaluation]] = {}
        for ev in self.evaluations:
            out.setdefault(ev.event_id, []).append(ev)
        return {k: tuple(v) for k, v in out.items()}
