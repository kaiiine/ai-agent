"""Contrats d'audit versionnés (Lot 10). SÉPARÉS de `RecommendationResponse`
(gelée) : l'audit est un artefact parallèle. Le payload archive tout ce qui est
nécessaire pour comprendre ET rejouer une décision hors de l'état mutable du dépôt."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ..domain.candidates import CandidateEvaluation
from ..domain.recommendations import RecommendationResponse
from ..domain.requests import RecommendationRequest
from ..input_adapter.schema import AdaptedBatch

AUDIT_SCHEMA_VERSION = "1"


class ComboBookmakerAcceptanceStatus(Enum):
    """Statut EXPLICITE (jamais un booléen ambigu). En V1, aucune donnée -> NOT_VERIFIED."""

    NOT_VERIFIED = "NOT_VERIFIED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ComboMaterializationStatus(Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"                # builder non invoqué (allow_combos=False)
    NO_CANDIDATE = "NO_CANDIDATE"                    # invoqué, aucun combo admissible
    MATERIALIZED = "MATERIALIZED"                    # >=1 combo admissible sizé -> PortfolioLine COMBO
    ADMISSIBLE_NOT_MATERIALIZED = "ADMISSIBLE_NOT_MATERIALIZED"   # admissible mais non financé (caps/budget)
    # Conservé pour la DÉSÉRIALISATION d'audits historiques (avant ADR-ADV-014) ;
    # jamais produit par le code courant (le sizing COMBO existe désormais).
    BLOCKED_SIZING_NOT_AVAILABLE = "BLOCKED_SIZING_NOT_AVAILABLE"


@dataclass(frozen=True)
class ConfigSnapshot:
    config_name: str
    config_version: str
    checksum: str
    content: Mapping                                 # contenu EXACT archivé (autonome)


@dataclass(frozen=True)
class ComboPriceAudit:
    combo_id: str
    worst_case_ev: Decimal
    expected_value: Decimal
    combined_odds: Decimal
    combined_prob_mean: Decimal
    combined_prob_low: Decimal


@dataclass(frozen=True)
class ComboAuditTrail:
    """Faits Combo du Lot 9 conservés EXPLICITEMENT — jamais reconstruits depuis
    les PortfolioLine finales. Distingue les quatre situations (§13)."""

    builder_invoked: bool
    candidate_count: int
    admissible_count: int
    rejection_reasons: tuple[str, ...]
    admissible_combos: tuple[ComboPriceAudit, ...]
    safety_margin: Decimal | None
    combo_config_version: str | None
    bookmaker_acceptance_status: ComboBookmakerAcceptanceStatus
    materialization_status: ComboMaterializationStatus
    combo_signal: str | None                         # COMBO_SIZING_NOT_AVAILABLE le cas échéant


@dataclass(frozen=True)
class AdvisorAuditPayload:
    # Inputs de replay.
    request: RecommendationRequest
    config_snapshots: tuple[ConfigSnapshot, ...]
    adapted_batch: AdaptedBatch
    # Sorties intermédiaires + finale archivées (traçabilité + comparaison replay).
    policy_evaluations: tuple[CandidateEvaluation, ...]
    ranked_evaluations: tuple[CandidateEvaluation, ...]
    recommendation: RecommendationResponse
    combos: ComboAuditTrail
    be_run_id: str | None                            # identifiant d'exécution Betting Engine (None V1)


@dataclass(frozen=True)
class AdvisorAuditEnvelope:
    audit_schema_version: str
    audit_id: str
    request_id: str
    request_fingerprint: str
    created_at: datetime                             # métadonnée : hors identité/fingerprint
    payload_checksum: str
    payload: AdvisorAuditPayload
