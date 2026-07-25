"""Scoring qualité : data_quality statique par (provider, data_type), freshness_score dynamique."""

from __future__ import annotations
from datetime import datetime

# Confiance statique dans l'exactitude/complétude d'un provider pour un data_type
# (§5.2). v1 : table manuelle (PRD §8.2), pas encore calibrée sur données réelles.
DATA_QUALITY: dict[tuple[str, str], float] = {
    ("football_data_org", "FIXTURES"): 0.9,
    ("football_data_org", "RESULTS"): 0.9,
    ("football_data_org", "STANDINGS"): 0.9,
    ("api_sports", "FIXTURES"): 0.85,
    ("api_sports", "RESULTS"): 0.85,
    ("api_sports", "STANDINGS"): 0.85,
}

# Demi-vie de fraîcheur par data_type, en heures — passé ce délai, freshness_score ≈ 0.5.
FRESHNESS_HALF_LIFE_HOURS: dict[str, float] = {
    "FIXTURES": 12.0,
    "RESULTS": 24.0,
    "STANDINGS": 24.0,
}
DEFAULT_HALF_LIFE_HOURS = 12.0


def data_quality(provider: str, data_type: str) -> float:
    return DATA_QUALITY.get((provider, data_type), 0.5)  # inconnu → prudence


def freshness_score(effective_data_time: datetime, reference_time: datetime, data_type: str) -> float:
    """Décroissance exponentielle : 1.0 à l'instant, ~0.5 après une demi-vie.

    `effective_data_time` = published_time si dispo, sinon event_time — jamais
    fetched_at seul (une donnée récupérée à l'instant peut décrire un classement
    vieux de plusieurs jours).
    """
    half_life = FRESHNESS_HALF_LIFE_HOURS.get(data_type, DEFAULT_HALF_LIFE_HOURS)
    age_hours = max((reference_time - effective_data_time).total_seconds() / 3600, 0)
    return round(0.5 ** (age_hours / half_life), 4)
