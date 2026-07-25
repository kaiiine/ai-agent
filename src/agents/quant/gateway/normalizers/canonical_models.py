"""Conteneurs de transport génériques.

Les faits canoniques football (CanonicalMatch, CanonicalStandingRow + helpers)
vivent dans sports/football/canonical_facts.py (C1) ; ils sont ré-exportés ici
car fallback_chain et les normalizers les importent depuis ce module.

CanonicalPayload est la sortie d'un normalizer (payload d'une CanonicalEnvelope).
La DataEnvelope v1 a été retirée à C7 : la gateway ne renvoie plus que des
CanonicalEnvelope (canonical/envelope.py).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

# Ré-export des faits (C1) — fallback_chain et les normalizers importent d'ici.
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
    """Sortie d'un normalizer — payload d'une CanonicalEnvelope."""
    kind: str  # "fixtures" | "standings"
    matches: list[CanonicalMatch] = field(default_factory=list)
    standings: list[CanonicalStandingRow] = field(default_factory=list)
    event_time: datetime | None = None
    published_time: datetime | None = None
