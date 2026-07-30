"""Scoring qualité : data_quality statique par (provider, data_type), freshness_score dynamique.

Les demi-vies de fraîcheur ne sont plus codées en dur ici : elles vivent dans
`configs/gateway/freshness_policy.json` (versionné, checksum), chargées via
`freshness_policy.py`. Les VALEURS restent identiques à l'historique (12/24/24h,
défaut 12h) — seule leur provenance change (config inspectable au lieu d'un dict
module). La FORMULE (décroissance exponentielle) reste ici.
"""

from __future__ import annotations
from datetime import datetime

from src.agents.quant.gateway.core.freshness_policy import (
    FreshnessPolicy,
    default_freshness_policy,
)

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


def data_quality(provider: str, data_type: str) -> float:
    return DATA_QUALITY.get((provider, data_type), 0.5)  # inconnu → prudence


def freshness_score(
    effective_data_time: datetime,
    reference_time: datetime,
    data_type: str,
    *,
    policy: FreshnessPolicy | None = None,
) -> float:
    """Décroissance exponentielle : 1.0 à l'instant, ~0.5 après une demi-vie.

    `effective_data_time` = published_time si dispo, sinon event_time — jamais
    fetched_at seul (une donnée récupérée à l'instant peut décrire un classement
    vieux de plusieurs jours). La demi-vie vient de la politique versionnée
    (injectable ; défaut = politique du processus).
    """
    policy = policy or default_freshness_policy()
    half_life = policy.half_life_for(data_type)
    age_hours = max((reference_time - effective_data_time).total_seconds() / 3600, 0)
    return round(0.5 ** (age_hours / half_life), 4)
