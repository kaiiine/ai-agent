"""`OddsSnapshot` — une cote canonique observée sur une sélection (§5.3).

Neutre : la `selection` est CANONIQUE (`home`/`draw`/`away`, `player_a`...), pas
un slot bookmaker. Le pont `RawSelection`(slot) -> `OddsSnapshot`(rôle), via le
`ParticipantRoleResolver`, n'est pas encore construit (bloquant end-to-end
Winamax, cf. todos) : en attendant, un `OddsSnapshot` est fourni par un appelant
déjà canonicalisé ou construit dans les tests.

Les champs d'offre boostée (`boost_reference_odds`/`max_stake`/`max_payout`) sont
présents pour compléter le contrat (ADR-017) mais NON utilisés en V0 : le
value_engine refuse explicitement une offre `is_boosted` (Vague 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OddsSnapshot:
    event_id: str                          # canonical_event_id — « même événement »
    market_type: str                       # « même marché » (ex. "MATCH_WINNER")
    selection: str                         # canonique : "home"/"draw"/"away"...
    decimal_odds: float
    observed_at: datetime
    bookmaker: str
    is_boosted: bool = False
    boost_reference_odds: float | None = None   # Vague 2 — non lu en V0
    max_stake: float | None = None               # Vague 2 — non lu en V0
    max_payout: float | None = None              # Vague 2 — non lu en V0
