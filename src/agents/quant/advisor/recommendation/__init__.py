"""Recommandation V1 : produit une `RecommendationResponse` (au plus une ligne
SINGLE misée sur le meilleur candidat classé), sizing fractional-Kelly prudent,
explication structurée et audit structurel. Zéro recommandation autorisé."""

from .audit import build_audit_record
from .engine import recommend
from .simple import SizingProfile, compute_single_stake, load_sizing_profiles

__all__ = [
    "recommend", "build_audit_record",
    "SizingProfile", "compute_single_stake", "load_sizing_profiles",
]
