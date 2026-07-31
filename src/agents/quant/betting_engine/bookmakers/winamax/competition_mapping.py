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

# "roster_overlap" : désambiguïsation déterministe par chevauchement de roster
# (competition_identity.disambiguate) — preuve plus forte qu'un nom, cf. les 2 « Bundesliga ».
_VERIFICATION_METHODS = {"manual", "snapshot", "live_call", "roster_overlap", "unverified"}


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
        "33", "competition:football:ita:serie_a", _VERIFIED, "live_call",
        "carto §3 : tournamentId 33 = « Serie A » (scan live 2026-07-31) ; équipes Serie A "
        "peuplées au registre (IDs football_data_org vérifiés en direct, endpoint SA/matches)",
    ),
    WinamaxCompetitionMapping(
        "36", "competition:football:esp:laliga", _VERIFIED, "roster_overlap",
        "tid 36 = « LaLiga » confirmé par chevauchement de roster (0.75 vs PD, "
        "competition_identity.disambiguate) ; équipes peuplées (IDs football_data_org PD)",
    ),
    WinamaxCompetitionMapping(
        # DÉSAMBIGUÏSATION homonyme : tid 42 (0.556 vs BL1 allemand) vs tid 29 (0.0 =
        # Bundesliga AUTRICHIENNE). tid 42 retenu par roster, JAMAIS par le nom seul (§9).
        "42", "competition:football:deu:bundesliga", _VERIFIED, "roster_overlap",
        "tid 42 = « Bundesliga » (Allemagne) désambiguïsé par roster (0.556 vs BL1 ; "
        "tid 29 autrichien = 0.0) ; équipes peuplées (IDs football_data_org BL1)",
    ),
    WinamaxCompetitionMapping(
        "2", "competition:football:eng:championship", _VERIFIED, "roster_overlap",
        "tid 2 = « Championship » confirmé par roster (0.83 vs ELC) ; équipes peuplées (ELC)",
    ),
    WinamaxCompetitionMapping(
        "39", "competition:football:nld:eredivisie", _VERIFIED, "roster_overlap",
        "tid 39 = « Eredivisie » confirmé par roster (0.61 vs DED) ; équipes peuplées (DED)",
    ),
    WinamaxCompetitionMapping(
        "52", "competition:football:prt:primeira_liga", _VERIFIED, "roster_overlap",
        "tid 52 = « Liga Portugal » confirmé par roster (0.88 vs PPL) ; équipes peuplées (PPL)",
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
