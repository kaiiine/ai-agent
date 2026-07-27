"""Rattachement événement Winamax -> identité canonique (bookmaker_registry).

Hermétique : IdentityResolver monté à la main + résolveur de compétition injecté
(la table réelle est testée séparément).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.gateway.core.identity_resolver import CanonicalEntity, IdentityResolver
from src.agents.quant.betting_engine.bookmakers.protocol import RawBookmakerEvent
from src.agents.quant.betting_engine.bookmakers.bookmaker_registry import (
    BookmakerEventResolver,
    SEVERITY_ORDER,
    most_severe,
)

_KO = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)


def _resolver() -> BookmakerEventResolver:
    entities = [
        # PSG : porte un ID Winamax (85) pour tester le seam by-ID et le CONFLICT.
        CanonicalEntity("team:football:fra:psg", "Paris Saint Germain",
                        ["PSG", "Paris SG", "Paris Saint-Germain"], {"winamax": "85"}),
        CanonicalEntity("team:football:fra:marseille", "Marseille",
                        ["OM", "Olympique Marseille"], {}),
        # Deux "United" partageant l'alias "United" -> ambiguïté réelle.
        CanonicalEntity("team:football:eng:united_a", "United A", ["United"], {}),
        CanonicalEntity("team:football:eng:united_b", "United B", ["United"], {}),
    ]
    identity = IdentityResolver(entities)
    comp = lambda tid: (
        ("competition:football:fra:ligue1", "RESOLVED", "competition_table")
        if tid == "4" else (None, "UNRESOLVED", "none")
    )
    return BookmakerEventResolver(identity, competition_resolver=comp)


def _event(**kw) -> RawBookmakerEvent:
    base = dict(
        bookmaker="winamax", bookmaker_event_id="E1", sport="football",
        competition="Ligue 1", slot_1_name="Paris Saint-Germain", slot_2_name="Marseille",
        slot_1_id=None, slot_2_id=None, start_time=_KO, status="PREMATCH",
        is_outright=False, markets=[], fetched_at=_KO, raw_tournament_id="4",
    )
    base.update(kw)
    return RawBookmakerEvent(**base)


# --- Point 6 : ordre de sévérité EXACT ---------------------------------------
def test_severity_order_is_exactly_conflict_ambiguous_unresolved_resolved():
    assert SEVERITY_ORDER == ("RESOLVED", "UNRESOLVED", "AMBIGUOUS", "CONFLICT")
    assert most_severe(["RESOLVED", "UNRESOLVED"]) == "UNRESOLVED"
    assert most_severe(["UNRESOLVED", "AMBIGUOUS"]) == "AMBIGUOUS"
    assert most_severe(["AMBIGUOUS", "CONFLICT"]) == "CONFLICT"
    assert most_severe(["RESOLVED", "RESOLVED", "RESOLVED"]) == "RESOLVED"


def test_fully_resolved_event_is_usable_with_canonical_key():
    m = _resolver().resolve_event(_event())
    assert m.identity_status == "RESOLVED"
    assert m.eligibility_status == "ELIGIBLE"
    assert m.is_usable is True
    assert m.competition_id == "competition:football:fra:ligue1"
    # clé canonique par rôle (PSG à domicile via ParticipantRoleResolver, ADR-015)
    assert m.canonical_event_id is not None
    assert "home=psg" in m.canonical_event_id and "away=marseille" in m.canonical_event_id
    # une preuve par sous-résolution
    assert len(m.evidence) == 3
    assert {e.subject for e in m.evidence} == {"slot_1", "slot_2", "competition"}
    slot1 = next(e for e in m.evidence if e.subject == "slot_1")
    assert (slot1.method, slot1.status, slot1.canonical_id) == (
        "name_alias", "RESOLVED", "team:football:fra:psg")


def test_unresolved_participant_blocks_the_event():
    m = _resolver().resolve_event(_event(slot_1_name="Copenhague"))  # absent du registre
    assert m.identity_status == "UNRESOLVED"
    assert m.canonical_event_id is None
    assert m.is_usable is False
    slot1 = next(e for e in m.evidence if e.subject == "slot_1")
    assert slot1.status == "UNRESOLVED" and slot1.method == "none"


def test_ambiguous_name_never_silently_picks_one():
    m = _resolver().resolve_event(_event(slot_1_name="United"))
    assert m.identity_status == "AMBIGUOUS"
    assert m.canonical_event_id is None
    slot1 = next(e for e in m.evidence if e.subject == "slot_1")
    assert slot1.status == "AMBIGUOUS"
    assert slot1.canonical_id is None
    assert set(slot1.candidates) == {"team:football:eng:united_a", "team:football:eng:united_b"}


# --- Correspondance EXACTE : un quasi-match échoue, un alias enregistré réussit
def test_unregistered_near_alias_never_matches():
    # "Paris S-G" n'est PAS un alias enregistré (les alias sont PSG / Paris SG /
    # Paris Saint-Germain) : malgré la proximité visuelle, il ne doit pas matcher.
    m = _resolver().resolve_event(_event(slot_1_name="Paris S-G"))
    slot1 = next(e for e in m.evidence if e.subject == "slot_1")
    assert slot1.status == "UNRESOLVED"
    assert slot1.canonical_id is None


def test_registered_alias_matches_exactly():
    m = _resolver().resolve_event(_event(slot_1_name="Paris SG"))   # alias enregistré
    slot1 = next(e for e in m.evidence if e.subject == "slot_1")
    assert slot1.status == "RESOLVED"
    assert slot1.method == "name_alias"
    assert slot1.canonical_id == "team:football:fra:psg"


# --- Seam by-ID : prioritaire, et désaccord ID/nom = CONFLICT -----------------
def test_provider_id_takes_priority_when_name_agrees():
    m = _resolver().resolve_event(_event(slot_1_id="85", slot_1_name="Paris SG"))
    slot1 = next(e for e in m.evidence if e.subject == "slot_1")
    assert slot1.method == "provider_id"
    assert slot1.status == "RESOLVED"
    assert slot1.canonical_id == "team:football:fra:psg"


def test_id_and_name_disagreement_is_conflict_not_silent_choice():
    # ID 85 -> PSG, mais le nom dit "Marseille" -> CONFLICT, jamais un choix muet.
    m = _resolver().resolve_event(_event(slot_1_id="85", slot_1_name="Marseille"))
    assert m.identity_status == "CONFLICT"          # le pire l'emporte
    assert m.canonical_event_id is None
    slot1 = next(e for e in m.evidence if e.subject == "slot_1")
    assert slot1.status == "CONFLICT"
    assert set(slot1.candidates) == {"team:football:fra:psg", "team:football:fra:marseille"}


# --- Point 5 : éligibilité SÉPARÉE de l'identité ------------------------------
def test_outright_is_ineligible_by_type_not_conflated_with_identity():
    m = _resolver().resolve_event(_event(is_outright=True, slot_1_name="", slot_2_name=""))
    assert m.eligibility_status == "UNSUPPORTED_EVENT_TYPE"
    assert m.identity_status == "UNRESOLVED"        # champ distinct, non fusionné
    assert m.canonical_event_id is None
    assert m.is_usable is False


def test_unresolved_competition_also_blocks_event():
    m = _resolver().resolve_event(_event(raw_tournament_id="999"))  # comp inconnue
    assert m.identity_status == "UNRESOLVED"
    comp = next(e for e in m.evidence if e.subject == "competition")
    assert comp.status == "UNRESOLVED"
    assert m.canonical_event_id is None
