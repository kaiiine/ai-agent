"""Clé canonique d'un événement pariable — fonction unique, indépendante du bookmaker.

Un même match doit produire la MÊME clé quel que soit l'ordre d'affichage du
bookmaker (§5.2bis) : la clé encode donc les participants par leur **rôle**
canonique (`home`/`away`, `player_a`/`player_b`...), jamais un tri de slugs qui
perdrait l'information de rôle. `scheduled_at` est ramené en UTC.

Isolée ici, sans dépendre des objets qui la consomment, pour être testée seule.
"""

from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Iterable


def build_canonical_event_key(
    sport: str,
    competition_id: str,
    scheduled_at: datetime,
    participants_with_roles: Iterable[tuple[str, str]],
) -> str:
    """Construit une clé déterministe `event:{sport}:{comp}:{utc}:{rôles}`.

    `participants_with_roles` : itérable de `(role, canonical_id)`. L'ordre
    d'entrée n'a aucune importance — les participants sont ordonnés par rôle, et
    le rôle est conservé explicitement dans la clé. `scheduled_at` doit être
    timezone-aware ; il est normalisé en UTC (une heure locale ambiguë est
    rejetée plutôt que devinée).
    """
    if scheduled_at.tzinfo is None:
        raise ValueError("scheduled_at doit être timezone-aware (UTC attendu).")

    pairs = list(participants_with_roles)
    if any(role is None or cid is None for role, cid in pairs):
        raise ValueError(
            "build_canonical_event_key exige un rôle ET un canonical_id pour "
            f"chaque participant : {pairs!r}"
        )

    when = scheduled_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    comp_slug = competition_id.split(":")[-1]
    # tri par (role, slug) : déterministe, indépendant de l'ordre bookmaker, et
    # le rôle reste lisible dans la clé.
    participants = "|".join(
        f"{role}={cid.split(':')[-1]}" for role, cid in sorted(pairs)
    )
    return f"event:{sport}:{comp_slug}:{when}:{participants}"
