"""Pont : événement bookmaker résolu -> `CanonicalEvent` (§4.2).

Combine ce que produisent les deux étapes précédentes, sans les mélanger :
- l'**identité** (`canonical_id` par slot) vient du `BookmakerEventMapping` (evidence) ;
- le **rôle** sportif par slot vient du `ParticipantRoleResolver` (ADR-015).

Ne renvoie un `CanonicalEvent` que si le rattachement est consommable
(`is_usable` : identité RESOLVED + événement ELIGIBLE) ; sinon `None` (l'événement
part en file de revue, jamais utilisé tel quel).
"""

from __future__ import annotations

from src.agents.quant.betting_engine.core.canonical_event import (
    CanonicalEvent,
    CanonicalParticipant,
)

from .bookmaker_registry import BookmakerEventMapping
from .participant_role_resolver import ParticipantRoleResolver
from .protocol import RawBookmakerEvent


def build_canonical_event(
    raw_event: RawBookmakerEvent,
    mapping: BookmakerEventMapping,
    role_resolver: ParticipantRoleResolver | None = None,
) -> CanonicalEvent | None:
    if not mapping.is_usable or raw_event.start_time is None:
        return None

    resolver = role_resolver or ParticipantRoleResolver()
    role_by_slot = {p.bookmaker_slot: p.role for p in resolver.resolve(raw_event)}
    cid_by_slot = {
        e.subject: e.canonical_id
        for e in mapping.evidence
        if e.subject in ("slot_1", "slot_2")
    }

    participants = tuple(
        CanonicalParticipant(canonical_id=cid_by_slot[slot], role=role_by_slot[slot])
        for slot in ("slot_1", "slot_2")
    )
    return CanonicalEvent(
        event_id=mapping.canonical_event_id,
        sport=mapping.sport,
        competition_id=mapping.competition_id,
        participants=participants,
        scheduled_at=raw_event.start_time,
    )
