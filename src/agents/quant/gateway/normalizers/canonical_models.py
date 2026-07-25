"""Conteneurs de transport génériques + shim de transition (Vague 0).

Les faits canoniques football (CanonicalMatch, CanonicalStandingRow + helpers)
ont été déplacés vers sports/football/canonical_facts.py (étape C1). Ils sont
ré-exportés ici pour ne pas casser les importeurs existants (fallback_chain,
protocol) pendant la transition — la bascule finale vers CanonicalEnvelope se
fait à C7.

CanonicalPayload et DataEnvelope restent ici : conteneurs génériques encore
utilisés par le pipeline v1.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

# Ré-export des faits déplacés (transition C1) — fallback_chain et les normalizers
# continuent d'importer ces symboles depuis ce module sans changement.
from src.agents.quant.gateway.sports.football.canonical_facts import (  # noqa: F401
    CanonicalMatch,
    CanonicalStandingRow,
    match_to_dict,
    match_from_dict,
    standing_to_dict,
    standing_from_dict,
)


@dataclass(frozen=True)
class CanonicalPayload:
    """Sortie d'un normalizer — ce que la gateway enveloppe ensuite (DataEnvelope v1)."""
    kind: str  # "fixtures" | "standings"
    matches: list[CanonicalMatch] = field(default_factory=list)
    standings: list[CanonicalStandingRow] = field(default_factory=list)
    event_time: datetime | None = None
    published_time: datetime | None = None


@dataclass(frozen=True)
class DataEnvelope:
    """Réponse finale v1 servie aux consommateurs — remplacée par CanonicalEnvelope à C7."""
    payload: CanonicalPayload
    provider: str

    event_time: datetime | None
    published_time: datetime | None
    available_to_model_time: datetime
    fetched_at: datetime
    ingested_at: datetime

    data_quality: float
    freshness_score: float
    stale: bool = False
