"""Correspondance tournoi Winamax -> compétition canonique (gateway).

Même discipline que le `ProviderCompetitionCoverage` de la gateway : une entrée
n'est **utilisable que si elle porte une preuve de vérification**
(`verified_at` + `verification_method`). Une entrée non vérifiée existe pour
mémoire mais n'est JAMAIS servie — elle résout comme si elle était absente.

Winamax n'expose pas le `canonical_id` de compétition ; ce rattachement est
posé à la main, vérifié contre le `tournamentName` du snapshot réel (carto §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

_VERIFICATION_METHODS = {"manual", "snapshot", "live_call", "unverified"}


@dataclass(frozen=True)
class WinamaxCompetitionMapping:
    winamax_tournament_id: str
    competition_id: str                    # canonical, référence competition_registry (gateway)
    verified_at: datetime | None
    verification_method: str               # manual | snapshot | live_call | unverified
    note: str = ""

    def __post_init__(self) -> None:
        if self.verification_method not in _VERIFICATION_METHODS:
            raise ValueError(
                f"verification_method invalide : {self.verification_method!r} "
                f"(attendu {sorted(_VERIFICATION_METHODS)})"
            )

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None and self.verification_method != "unverified"


_VERIFIED = datetime(2026, 7, 26, tzinfo=timezone.utc)

# Seed : uniquement des compétitions dont les équipes sont peuplées dans
# l'identity_resolver (Ligue 1, Premier League). Serie A est là pour mémoire
# mais NON vérifiée -> inutilisable tant que non vérifiée (démontre la règle).
WINAMAX_COMPETITION_MAPPINGS: list[WinamaxCompetitionMapping] = [
    WinamaxCompetitionMapping(
        "4", "competition:football:fra:ligue1", _VERIFIED, "snapshot",
        "carto §3 : tournamentId 4 = « Ligue 1 McDonald's® »",
    ),
    WinamaxCompetitionMapping(
        "1", "competition:football:eng:premier_league", _VERIFIED, "snapshot",
        "carto §3 : tournamentId 1 = « Premier League »",
    ),
    WinamaxCompetitionMapping(
        "33", "competition:football:ita:serie_a", None, "unverified",
        "à vérifier : équipes Serie A pas encore au registre",
    ),
]

_BY_TID: dict[str, WinamaxCompetitionMapping] = {
    m.winamax_tournament_id: m for m in WINAMAX_COMPETITION_MAPPINGS
}


def resolve_competition(
    winamax_tournament_id: str | None,
) -> tuple[str | None, str, str]:
    """`(competition_id | None, status, method)`.

    - inconnu          -> (None, "UNRESOLVED", "none")
    - connu non vérifié -> (None, "UNRESOLVED", "unverified")  # jamais servi sans preuve
    - connu vérifié     -> (competition_id, "RESOLVED", "competition_table")
    """
    if winamax_tournament_id is None:
        return None, "UNRESOLVED", "none"
    mapping = _BY_TID.get(str(winamax_tournament_id))
    if mapping is None:
        return None, "UNRESOLVED", "none"
    if not mapping.is_verified:
        return None, "UNRESOLVED", "unverified"
    return mapping.competition_id, "RESOLVED", "competition_table"
