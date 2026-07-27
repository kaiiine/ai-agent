"""`CanonicalEvent` — événement pariable identifié indépendamment de tout bookmaker (§5.2).

Contrat générique : produit par la couche d'acquisition (à partir d'un
`BookmakerEventMapping` résolu, cf. `bookmakers/canonical_binding.py`) et
consommé par la couche sport (`feature_engineering`). Le `canonical_id` de
chaque participant est résolu via la gateway ; son `role` sportif est fourni par
le `ParticipantRoleResolver` (identité ≠ rôle, cf. ADR-015 et §5.2bis).

NB : la fonction de frappe de la clé (`build_canonical_event_key`) vit pour
l'instant dans `bookmakers/canonical_event.py` (où elle est utilisée pour poser
`canonical_event_id`) ; elle pourra être remontée ici lors d'un nettoyage
ultérieur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CanonicalParticipant:
    canonical_id: str                      # typé, résolu via la gateway (identity_resolver)
    role: str                              # "home"/"away", "player_a"/"player_b"... (sport)


@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    sport: str
    competition_id: str                    # référence competition_registry (gateway)
    participants: tuple[CanonicalParticipant, ...]
    scheduled_at: datetime
    context: object | None = None          # EventContext typé/versionné (context_schema.py) — à venir
