"""Score de BASE d'un candidat (ADR-ADV-005 D1/D4), indépendant de l'ordre
d'entrée : `base_score = value × reliability × quality × freshness × liquidity −
uncertainty_penalty`

La probabilité N'ENTRE PAS dans ce produit, volontairement. Une version l'y a
multipliée avec un poids par profil ; ces poids ne venaient d'aucun banc de
mesure, et un mélange pondéré laisse toujours un gros EV racheter une
probabilité nettement plus faible. La sécurité se traite par l'ORDRE.

DETTE CONNUE : le chemin de revue applique déjà cet ordre lexicographique
(`markets/review_ranking.Posture`). Ce chemin-ci, celui de la MISE, ne le fait
pas encore — il est inatteignable tant qu'aucun modèle n'est SUPPORTED. Le jour
où il le devient, il doit adopter la même posture, sans quoi le classement
misable retombera sur « ce qui rapporte » au lieu de « ce qui passe ».. Le `concentration_penalty` (séquentiel) est appliqué plus
tard par `sort.py`. `policy_component` est retiré (D1)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..domain.candidates import CandidateBet
from . import components
from .profiles import RankingProfile


@dataclass(frozen=True)
class BaseScore:
    base_score: Decimal
    components: dict[str, Decimal]         # décomposition (hors concentration)


def score_base(candidate: CandidateBet, profile: RankingProfile) -> BaseScore:
    """Peut lever `components.NonRankable` si un input REQUIRED manque."""
    value = components.value_component(candidate.expected_value_low, profile)
    reliability = components.reliability_component(
        candidate.model_maturity, candidate.calibration_score, profile)
    quality = components.quality_component(candidate.data_quality)
    freshness = components.freshness_component(candidate.freshness_score, profile)
    liquidity = components.liquidity_component(candidate.liquidity_score, profile)
    uncertainty = components.uncertainty_penalty(
        candidate.probability_low, candidate.probability_high, profile)

    product = value * reliability * quality * freshness * liquidity
    base = product - uncertainty
    return BaseScore(
        base_score=base,
        components={
            "value_component": value,
            "reliability_component": reliability,
            "quality_component": quality,
            "freshness_component": freshness,
            "liquidity_component": liquidity,
            "uncertainty_penalty": uncertainty,
        },
    )
