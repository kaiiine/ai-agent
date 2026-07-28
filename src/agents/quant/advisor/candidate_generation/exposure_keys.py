"""Clés d'exposition STRUCTURELLES (ADR-ADV-008).

Vocabulaire canonique figé :

    event:<id>
    participant:<id>
    competition:<id>
    market:<type>
    bookmaker:<id>

Purement dérivé de l'identité déjà résolue — aucune donnée nouvelle. Sert au
`concentration_penalty` (Lot 5) et aux contraintes de portefeuille (Lot 8) à
détecter un risque partagé (faux sentiment de diversification)."""

from __future__ import annotations


def exposure_keys_for(
    *, event_id: str, competition_id: str, market_type: str, bookmaker: str,
    participant_ids: tuple[str, ...],
) -> frozenset[str]:
    keys = {
        f"event:{event_id}",
        f"competition:{competition_id}",
        f"market:{market_type}",
        f"bookmaker:{bookmaker}",
    }
    keys.update(f"participant:{pid}" for pid in participant_ids)
    return frozenset(keys)
