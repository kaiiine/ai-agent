"""Sizing COMBO V1 (ADR-ADV-014). RÉUTILISE le Kelly canonique du Lot 6
(`compute_single_stake`) — AUCUNE 2e formule money.

Le combo est représenté comme un `CandidateBet` SYNTHÉTIQUE :
  probability_low = combined_prob_low   (borne basse ; JAMAIS combined_prob_mean)
  bookmaker_odds  = combined_odds
  data_quality    = min des jambes
  calibration/reliability = min des jambes (conservateur)
  exposure_keys   = UNION des jambes  -> la mise compte sur CHAQUE jambe (§4)
  maturity        = SUPPORTED ssi TOUTES les jambes le sont (sinon aucune mise)

La `safety_margin` (Lot 9) est déjà incorporée dans `combined_prob_low` par le
pricing : elle n'est JAMAIS réappliquée au stake. Le conservatisme combo passe par
`combo_fractional_kelly` + les caps d'exposition, pas par une 2e correction de proba.
"""

from __future__ import annotations

from decimal import Context, Decimal

from ..domain.candidates import CandidateBet
from ..domain.money import ONE, ZERO
from ..recommendation.simple import SizingProfile
from .builder import ComboEvaluation

_CTX = Context(prec=28)


def combo_sizing_profile(profile: SizingProfile) -> SizingProfile:
    """Profil de sizing COMBO dérivé du profil de risque : le Kelly fractionné et le
    cap par ligne prennent leurs valeurs COMBO (plus conservatrices). Passé tel quel
    à `compute_single_stake` -> réutilise la formule canonique sans duplication."""
    if profile.combo_fractional_kelly is None or profile.combo_line_cap_fraction is None:
        raise ValueError("profil de sizing sans paramètres COMBO : combo non sizable")
    return SizingProfile(
        fractional_kelly=profile.combo_fractional_kelly,
        per_line_cap_fraction=profile.combo_line_cap_fraction,
        combo_fractional_kelly=profile.combo_fractional_kelly,
        combo_line_cap_fraction=profile.combo_line_cap_fraction,
    )


def combo_reliability(combo: ComboEvaluation) -> Decimal:
    """Reliability du combo = MIN des `reliability_component` des jambes (conservateur).
    Le ranking a déjà résolu une jambe sans calibration_score en baseline."""
    return min(leg.ranking_components["reliability_component"] for leg in combo.legs)


def build_combo_candidate(combo: ComboEvaluation) -> CandidateBet:
    """`CandidateBet` synthétique représentant le combo pour le sizing/exposition.
    Tous les invariants de `CandidateBet` sont respectés (bornes de proba, odds > 1)."""
    if combo.pricing is None:
        raise ValueError("combo non pricé : sizing impossible")
    pricing = combo.pricing
    legs = [leg.candidate for leg in combo.legs]

    maturities = {c.model_maturity for c in legs}
    maturity = "SUPPORTED" if maturities == {"SUPPORTED"} else sorted(maturities)[0]
    exposure_keys = frozenset().union(*(c.exposure_keys for c in legs))
    participant_ids = tuple(sorted(set().union(*(c.participant_ids for c in legs))))
    # Fraîcheur combo = min des jambes si les deux présentes, sinon None (jamais 0).
    freshness = [c.freshness_score for c in legs]
    combo_freshness = min(freshness) if all(f is not None for f in freshness) else None

    implied = _CTX.divide(ONE, pricing.combined_odds)
    fair_odds = _CTX.divide(ONE, pricing.combined_prob_mean) if pricing.combined_prob_mean > ZERO else pricing.combined_odds

    return CandidateBet(
        candidate_id=combo.combo_id,
        event_id="+".join(sorted(c.event_id for c in legs)),
        sport=legs[0].sport, competition_id=legs[0].competition_id,
        scheduled_at=min(c.scheduled_at for c in legs),
        bookmaker=legs[0].bookmaker, market_id=combo.combo_id, market_type="COMBO",
        selection=combo.combo_id,
        bookmaker_odds=pricing.combined_odds,
        fair_probability=pricing.combined_prob_mean,
        probability_low=pricing.combined_prob_low,
        probability_high=pricing.combined_prob_mean,      # low <= fair == high (valide)
        fair_odds=fair_odds, implied_probability=implied,
        expected_value_mean=pricing.expected_value, expected_value_low=pricing.worst_case_ev,
        edge_mean=ZERO, edge_low=ZERO, model_version="combo.v1", model_maturity=maturity,
        calibration_score=combo_reliability(combo), data_quality=combo.min_leg_quality,
        freshness_score=combo_freshness, liquidity_score=None,
        max_stake=None, max_payout=None, is_boosted=False,
        participant_ids=participant_ids, exposure_keys=exposure_keys,
        warnings=(), explanation_ref=combo.combo_id, source_decision_id=None,
    )
