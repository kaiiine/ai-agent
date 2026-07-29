"""Construction de l'enregistrement d'audit (Lot 10 §13/§14) en PARALLÈLE de
`RecommendationResponse` (jamais dedans). Conserve explicitement les quatre états
Combo du Lot 9 — jamais déduits des PortfolioLine finales."""

from __future__ import annotations

from datetime import datetime, timezone

from ..policy import reason_codes
from . import canonical, identity
from .schema import (
    AUDIT_SCHEMA_VERSION,
    AdvisorAuditEnvelope,
    AdvisorAuditPayload,
    ComboAuditTrail,
    ComboBookmakerAcceptanceStatus,
    ComboMaterializationStatus,
    ComboPriceAudit,
    ConfigSnapshot,
)


def _combo_trail(trace) -> ComboAuditTrail:
    NOT_VERIFIED = ComboBookmakerAcceptanceStatus.NOT_VERIFIED   # aucune donnée bookmaker en V1
    if not trace.combo_builder_invoked:
        # État 1 : combos jamais recherchés (allow_combos=False).
        return ComboAuditTrail(
            builder_invoked=False, candidate_count=0, admissible_count=0, rejection_reasons=(),
            admissible_combos=(), safety_margin=None, combo_config_version=None,
            bookmaker_acceptance_status=NOT_VERIFIED,
            materialization_status=ComboMaterializationStatus.NOT_APPLICABLE, combo_signal=None)

    cr = trace.combo_result
    candidate_count = len(cr.admissible) + len(cr.rejected)
    policy = trace.combo_policy
    if not cr.admissible:
        # État 2 : invoqué mais aucun combo admissible.
        return ComboAuditTrail(
            builder_invoked=True, candidate_count=candidate_count, admissible_count=0,
            rejection_reasons=tuple(c.rejection_reason for c in cr.rejected if c.rejection_reason),
            admissible_combos=(), safety_margin=policy.safety_margin,
            combo_config_version=policy.config_version, bookmaker_acceptance_status=NOT_VERIFIED,
            materialization_status=ComboMaterializationStatus.NO_CANDIDATE, combo_signal=None)

    # États 3+4 : combo admissible, acceptation bookmaker NON vérifiée, bloqué au sizing.
    prices = tuple(ComboPriceAudit(
        c.combo_id, c.pricing.worst_case_ev, c.pricing.expected_value, c.pricing.combined_odds,
        c.pricing.combined_prob_mean, c.pricing.combined_prob_low) for c in cr.admissible)
    return ComboAuditTrail(
        builder_invoked=True, candidate_count=candidate_count, admissible_count=len(cr.admissible),
        rejection_reasons=tuple(c.rejection_reason for c in cr.rejected if c.rejection_reason),
        admissible_combos=prices, safety_margin=policy.safety_margin,
        combo_config_version=policy.config_version, bookmaker_acceptance_status=NOT_VERIFIED,
        materialization_status=ComboMaterializationStatus.BLOCKED_SIZING_NOT_AVAILABLE,
        combo_signal=reason_codes.COMBO_SIZING_NOT_AVAILABLE)


def build_envelope(
    request, adapted_batch, config_snapshots: tuple[ConfigSnapshot, ...], trace, recommendation,
    *, be_run_id: str | None = None, now=None,
) -> AdvisorAuditEnvelope:
    payload = AdvisorAuditPayload(
        request=request, config_snapshots=tuple(config_snapshots), adapted_batch=adapted_batch,
        policy_evaluations=tuple(trace.policy_evaluations),
        ranked_evaluations=tuple(trace.ranked_evaluations),
        recommendation=recommendation, combos=_combo_trail(trace), be_run_id=be_run_id)
    fingerprint = identity.request_fingerprint(request)
    return AdvisorAuditEnvelope(
        audit_schema_version=AUDIT_SCHEMA_VERSION,
        audit_id=identity.audit_id(request.request_id, fingerprint),
        request_id=request.request_id, request_fingerprint=fingerprint,
        created_at=now or datetime.now(timezone.utc),   # métadonnée : hors identité
        payload_checksum=canonical.checksum(payload), payload=payload)
