"""Énumérations du domaine Advisor (PRD §8)."""

from __future__ import annotations

from enum import Enum


class RiskProfile(Enum):
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"
    CUSTOM = "CUSTOM"


class MaturityPolicy(Enum):
    SUPPORTED_ONLY = "SUPPORTED_ONLY"
    INCLUDE_EXPERIMENTAL_FOR_REVIEW = "INCLUDE_EXPERIMENTAL_FOR_REVIEW"


class CandidateStatus(Enum):
    ELIGIBLE = "ELIGIBLE"
    REVIEW_ONLY = "REVIEW_ONLY"
    REJECTED = "REJECTED"


class LineType(Enum):
    SINGLE = "SINGLE"
    COMBO = "COMBO"


class RecommendationOutcome(Enum):
    RECOMMENDED = "RECOMMENDED"
    REVIEW_CANDIDATES = "REVIEW_CANDIDATES"
    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    NO_EVALUABLE_EVENTS = "NO_EVALUABLE_EVENTS"
    FAILED = "FAILED"
