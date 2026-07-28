"""Explication structurée d'une recommandation SINGLE (PRD §15.1). Textes
factuels : pourquoi ce candidat, pourquoi cette mise, risques et limites V1
assumées — jamais un argument de vente."""

from __future__ import annotations

from decimal import Decimal

from ..domain.candidates import CandidateEvaluation
from ..domain.portfolios import PortfolioExplanation


def build_single_explanation(top: CandidateEvaluation, stake: Decimal) -> PortfolioExplanation:
    c = top.candidate
    line_id = f"line:{c.candidate_id}"
    return PortfolioExplanation(
        summary="1 pari simple sur le meilleur candidat classé (V1 : ligne SINGLE).",
        selection_reasons={line_id: (
            "meilleur ranking_score parmi les ELIGIBLE",
            f"expected_value_low={c.expected_value_low}",
        )},
        allocation_reasons={line_id: (
            "fractional Kelly sur la borne basse (probability_low) × reliability × data_quality",
            "plafonné par bankroll / max_total_stake / max_stake / max_payout",
        )},
        rejected_alternatives=(),
        major_risks=(
            "incertitude du modèle (intervalle estimé)",
            "liquidité non exposée en V1 (escompte conservateur)",
        ),
        model_limitations=(
            "sizing V1 : ligne SINGLE uniquement ; caps multi-lignes/portefeuille, "
            "corrélation et granularité de mise = Lot 8",
        ),
    )
