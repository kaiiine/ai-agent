"""Contrat commun à tous les fournisseurs de données sportives.

Un provider transporte des données BRUTES (payload JSON tel quel) — il ne
construit jamais un DataEnvelope lui-même. La normalisation, la résolution
d'identité et le scoring qualité sont la responsabilité de la gateway, après
l'appel provider (voir gateway.py).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RawProviderResponse:
    payload: dict
    provider: str
    fetched_at: datetime
    request_metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCapabilities:
    fixtures: bool = False
    standings: bool = False
    recent_form: bool = False
    injuries: bool = False
    lineups: bool = False
    live: bool = False
    historical: bool = False


@runtime_checkable
class SportsDataProvider(Protocol):
    name: str
    supported_sports: list[str]
    query_cost: float  # coût estimé par requête, 0.0 si gratuit

    def capabilities(self, sport: str) -> ProviderCapabilities:
        """Ce que ce provider sait vraiment servir pour ce sport."""
        ...

    def is_available(self, sport: str, season: str) -> bool:
        """Vérifie sans requête coûteuse si ce provider peut répondre pour cette saison."""
        ...

    def fetch_league_fixtures(
        self,
        sport: str,
        provider_league_id: str,
        season: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> RawProviderResponse:
        """Récupération batch d'une compétition entière (préférée aux appels équipe par équipe).

        provider_league_id est déjà résolu par identity_resolver.resolve() en amont —
        un provider ne reçoit jamais de canonical_id.
        """
        ...

    def fetch_standings(self, sport: str, provider_league_id: str, season: str) -> RawProviderResponse:
        ...

    def get_rate_limit_status(self) -> dict:
        """Requêtes restantes / reset time, pour arbitrer le fallback."""
        ...
