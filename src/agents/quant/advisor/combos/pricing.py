"""Pricing d'un combo INDEPENDENT_ENOUGH (Lot 9). Deux scénarios DISTINCTS
(moyen/bas) — jamais confondus (sinon EV == worst_case_ev, incohérent avec les
lignes SINGLE).

L'indépendance n'étant pas prouvée, la marge de sécurité COMMUNE (`0 < margin < 1`)
s'applique aux deux scénarios. Probabilités sur `probability_low`/`fair_probability`
des legs — jamais de valeur manquante remplacée par une valeur favorable."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from ..domain.candidates import CandidateBet
from ..domain.money import ONE, ZERO


@dataclass(frozen=True)
class ComboPricing:
    combined_odds: Decimal
    combined_prob_mean: Decimal          # ajustée (× safety_margin)
    combined_prob_low: Decimal           # ajustée (× safety_margin)
    expected_value: Decimal
    worst_case_ev: Decimal
    joint_prob_mean_raw: Decimal         # brute (avant marge) — pour l'explication
    joint_prob_low_raw: Decimal


def _product(values: Sequence[Decimal]) -> Decimal:
    out = ONE
    for v in values:
        out *= v
    return out


def price_combo(legs: Sequence[CandidateBet], safety_margin: Decimal) -> ComboPricing:
    """Produit générique sur les legs (V1 : 2 legs). Invariants garantis :
    `0 <= combined_prob_low <= combined_prob_mean <= 1` et `EV >= worst_case_ev`."""
    combined_odds = _product([leg.bookmaker_odds for leg in legs])
    joint_mean_raw = _product([leg.fair_probability for leg in legs])
    joint_low_raw = _product([leg.probability_low for leg in legs])

    combined_prob_mean = joint_mean_raw * safety_margin
    combined_prob_low = joint_low_raw * safety_margin

    return ComboPricing(
        combined_odds=combined_odds,
        combined_prob_mean=combined_prob_mean,
        combined_prob_low=combined_prob_low,
        expected_value=combined_prob_mean * combined_odds - ONE,
        worst_case_ev=combined_prob_low * combined_odds - ONE,
        joint_prob_mean_raw=joint_mean_raw,
        joint_prob_low_raw=joint_low_raw,
    )
