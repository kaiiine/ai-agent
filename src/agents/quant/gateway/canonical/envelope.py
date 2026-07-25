"""`CanonicalEnvelope` — enveloppe de transport versionnée (PRD v2 §5.1).

Évolution de `DataEnvelope` (v1) : conserve tous ses champs à l'identique et
ajoute l'identité de la donnée (canonical_id, sport, competition_id, season,
data_type, schema_version) et la provenance fine (provider_entity_id).

Câblée à C7 : fallback_chain ne renvoie plus que des CanonicalEnvelope.

Peuplement réel des horodatages (C7) :
- published_time est extrait des payloads providers, de façon complémentaire :
  football-data.org horodate les MATCHS (lastUpdated), api_sports horodate les
  CLASSEMENTS (update). Quand le provider ne fournit rien pour ce data_type,
  published_time est None et `freshness_degraded=True` (signalé, jamais masqué).
- event_time reste None au niveau enveloppe : un batch (compétition entière) n'a
  pas d'événement unique — le coup d'envoi de chaque match est capturé au niveau
  FAIT (CanonicalMatch.kickoff), pas ici.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from src.agents.quant.gateway.canonical.data_types import is_valid_data_type

# Sur quel horodatage freshness_score est réellement calculé.
FreshnessBasis = Literal["published_time", "event_time", "fetched_at"]


@dataclass(frozen=True)
class CanonicalEnvelope:
    # --- Identité de la donnée (nouveau en v2) ---
    canonical_id: str
    sport: str
    competition_id: str | None       # référence competition_registry ; None si hors compétition
    season: str | None               # obligatoire dès qu'une compétition est concernée (§8.4)
    data_type: str                   # vocabulaire fermé §5.2
    schema_version: str              # ex. "football/1.0"

    # --- Payload (structure propre au sport, opaque pour core/) ---
    payload: object

    # --- Provenance ---
    provider: str
    provider_entity_id: str | None   # ID natif de l'entité chez le provider (audit / retour arrière)

    # --- Horodatages point-in-time (5 distincts, ADR-004) ---
    event_time: datetime | None
    published_time: datetime | None
    available_to_model_time: datetime   # référence du walk-forward
    fetched_at: datetime
    ingested_at: datetime

    # --- Qualité ---
    data_quality: float
    freshness_score: float
    freshness_basis: FreshnessBasis     # quel horodatage a servi (traçabilité)
    freshness_degraded: bool            # True si retombé sur fetched_at faute de published/event
    stale: bool = False

    def __post_init__(self) -> None:
        if not is_valid_data_type(self.data_type):
            raise ValueError(f"data_type hors vocabulaire fermé : {self.data_type!r}")


def resolve_freshness_basis(
    published_time: datetime | None,
    event_time: datetime | None,
    fetched_at: datetime,
) -> tuple[datetime, FreshnessBasis, bool]:
    """Choisit l'horodatage effectif pour freshness_score (arbitrage Vague 0).

    Ordre : published_time → event_time → fetched_at.
    On ne fabrique JAMAIS un horodatage absent : si le provider n'a fourni ni
    published_time ni event_time, on retombe sur fetched_at avec `degraded=True`,
    signalé explicitement dans l'enveloppe plutôt que masqué (le glossaire
    interdit fetched_at comme base « normale » de fraîcheur).
    """
    if published_time is not None:
        return published_time, "published_time", False
    if event_time is not None:
        return event_time, "event_time", False
    return fetched_at, "fetched_at", True
