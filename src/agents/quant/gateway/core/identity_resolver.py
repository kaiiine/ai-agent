"""Résolution d'identité entre providers — le chaînon manquant du fallback.

Sans ça, un fallback "a l'air" multi-provider mais ne l'est pas : un ID
équipe valide chez un provider n'a aucune raison d'être valide chez un autre.
Le registre est alimenté manuellement (pas de résolution automatique par nom,
trop fragile — ex. "PSG" vs "Paris SG").
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

IdentityStatus = Literal["RESOLVED", "UNRESOLVED", "AMBIGUOUS", "CONFLICT"]


@dataclass(frozen=True)
class CanonicalEntity:
    canonical_id: str              # ex. "team:psg"
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    identities: dict[str, str] = field(default_factory=dict)   # {"api_sports": "85", "football_data_org": "524"}
    valid_from: datetime | None = None


class IdentityResolver:
    """Registre en mémoire, chargé au démarrage depuis identity_registry_data."""

    def __init__(self, entities: list[CanonicalEntity]):
        self._by_canonical_id = {e.canonical_id: e for e in entities}
        # Clé (provider, entity_type, provider_id) — un même provider peut assigner
        # le même ID numérique à une ligue ET à une équipe (ex. api_sports "39" =
        # ligue Premier League ET équipe Wolves), il faut le type pour désambiguïser.
        self._by_provider_id: dict[tuple[str, str, str], str] = {}
        for entity in entities:
            entity_type = entity.canonical_id.split(":", 1)[0]
            for provider, provider_id in entity.identities.items():
                self._by_provider_id[(provider, entity_type, provider_id)] = entity.canonical_id

    def resolve(self, canonical_id: str, target_provider: str) -> str | None:
        """Traduit un ID canonique vers l'ID spécifique d'un provider."""
        entity = self._by_canonical_id.get(canonical_id)
        if entity is None:
            return None
        return entity.identities.get(target_provider)

    def canonicalize(self, provider: str, provider_id: str, entity_type: str) -> tuple[str | None, IdentityStatus]:
        """Traduit un ID provider vers l'ID canonique Axon, avec un statut explicite."""
        canonical_id = self._by_provider_id.get((provider, entity_type, provider_id))
        if canonical_id is None:
            return None, "UNRESOLVED"
        return canonical_id, "RESOLVED"

    def entity(self, canonical_id: str) -> CanonicalEntity | None:
        return self._by_canonical_id.get(canonical_id)

    def find_by_name(self, name: str) -> CanonicalEntity | None:
        """Cherche une entité par nom exact ou alias — utilisé pour la recherche
        utilisateur ("PSG", "Paris Saint-Germain"), PAS pour canonicaliser une
        réponse provider (ça, c'est le rôle de canonicalize())."""
        needle = name.strip().lower()
        for entity in self._by_canonical_id.values():
            if entity.canonical_name.lower() == needle:
                return entity
            if needle in (alias.lower() for alias in entity.aliases):
                return entity
        return None

    def all_entities(self, entity_type_prefix: str) -> list[CanonicalEntity]:
        return [e for e in self._by_canonical_id.values() if e.canonical_id.startswith(entity_type_prefix)]
