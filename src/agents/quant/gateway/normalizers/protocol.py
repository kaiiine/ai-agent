"""Interface commune aux normalizers — un adaptateur par provider, jamais un `if provider == ...`."""

from __future__ import annotations
from typing import Protocol

from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.normalizers.canonical_models import CanonicalPayload


class ProviderNormalizer(Protocol):
    def normalize_fixtures(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str, season: str
    ) -> CanonicalPayload:
        """Convertit une réponse brute fixtures vers le modèle canonique.

        `resolver` canonicalise les entités (équipes) reçues du provider — une
        entité non résolue est écartée du payload, jamais rattachée par proximité
        de nom (voir identity_resolver.canonicalize).
        """
        ...

    def normalize_standings(
        self, raw: RawProviderResponse, resolver: IdentityResolver, league_id: str
    ) -> CanonicalPayload:
        ...
