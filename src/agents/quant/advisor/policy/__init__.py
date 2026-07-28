"""Couche Policy : détermine si un candidat est ELIGIBLE / REVIEW_ONLY / REJECTED
(codes de rejet stables), sans classer ni allouer. Seuils versionnés en config."""

from .eligibility import (
    PolicyConfig,
    PolicyProfile,
    evaluate_candidates,
    evaluate_eligibility,
    load_policy_config,
)

__all__ = [
    "PolicyConfig", "PolicyProfile",
    "evaluate_eligibility", "evaluate_candidates", "load_policy_config",
]
