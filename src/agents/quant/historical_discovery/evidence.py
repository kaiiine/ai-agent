"""Format canonique multisport d'une rencontre historique.

UN NOYAU, PAS UN PLUS PETIT DÉNOMINATEUR COMMUN. Forcer football, tennis et
baseball dans la même sémantique de score détruirait l'information : 2-1 en
football, 3-6 6-4 7-5 en tennis et 4-3 en 11 manches ne se réduisent pas l'un à
l'autre. Ce qu'ils partagent vraiment : deux camps, une date, une issue, une
provenance. Le reste vit dans `sport_specific`, que seuls les adapters du sport
concerné savent lire.

L'ISSUE EST SÉPARÉE DU SCORE. `outcome` est l'étiquette qu'un modèle apprend
(`home`/`draw`/`away`, `p1`/`p2`…) ; `score` est la trace brute. Les confondre
obligerait chaque consommateur à réinterpréter un format par sport, et chaque
réinterprétation est une occasion de se tromper en silence.

PROVENANCE OBLIGATOIRE. Une observation sans source ni licence est inexploitable
même si elle est vraie : rien ne permet de dire si on avait le droit de s'en
servir, ni de la recontrôler. Les champs ne sont donc pas optionnels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

#: Statuts d'une rencontre. Seul FINISHED porte une issue apprenable.
STATUSES = frozenset({"FINISHED", "SCHEDULED", "POSTPONED", "CANCELLED", "WALKOVER"})


@dataclass(frozen=True)
class HistoricalMatchEvidence:
    """Une rencontre passée, telle qu'une source la rapporte.

    `participants` est ORDONNÉ et son sens dépend du sport : (domicile,
    extérieur) en football, (joueur1, joueur2) en tennis. L'ordre porte de
    l'information — l'avantage du terrain — et le perdre coûterait un signal
    réel. Les identités y sont celles de la SOURCE tant que la résolution n'a
    pas eu lieu ; c'est `identity_verified` qui dit laquelle on lit.
    """

    sport: str
    source: str                          # nom du provider/dataset, jamais « internet »
    source_event_id: str                 # identifiant stable CHEZ la source
    competition: str
    season: str
    participants: tuple[str, ...]
    scheduled_at: datetime
    status: str
    provenance: str                      # URL ou chemin exact d'où vient la ligne
    license: str                         # identifiant de licence VÉRIFIÉ (SPDX ou texte)
    retrieved_at: datetime
    outcome: str | None = None           # étiquette apprenable, None si non terminé
    score: str | None = None             # trace brute, telle qu'écrite par la source
    #: Horodatage revendiqué PAR LA SOURCE, quand elle en publie un. Distinct de
    #: `retrieved_at` : l'un dit quand la donnée a été produite, l'autre quand on
    #: l'a lue. Sans les deux, impossible de prouver l'absence de fuite (§9).
    observed_source_timestamp: datetime | None = None
    #: Vrai fuseau inconnu ? On l'écrit plutôt que de le supposer UTC.
    timezone_verified: bool = False
    sport_specific: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status inconnu : {self.status!r}")
        if len(self.participants) < 2:
            raise ValueError("une rencontre oppose au moins deux camps")
        if not self.source or not self.provenance or not self.license:
            raise ValueError("provenance incomplète : source, provenance et licence requises")
        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at doit porter un fuseau explicite")
        if self.status == "FINISHED" and self.outcome is None:
            raise ValueError("une rencontre terminée porte une issue")

    @property
    def is_learnable(self) -> bool:
        """Seule une rencontre terminée avec issue nourrit un walk-forward."""
        return self.status == "FINISHED" and self.outcome is not None

    @property
    def stable_key(self) -> tuple[str, str]:
        """Clé de la source — survit à un report de date, contrairement au couple
        (participants, date). C'est elle qui distingue « la même rencontre revue »
        de « une seconde rencontre »."""
        return (self.source, self.source_event_id)

    def as_dict(self) -> dict:
        return {
            "sport": self.sport,
            "source": self.source,
            "source_event_id": self.source_event_id,
            "competition": self.competition,
            "season": self.season,
            "participants": list(self.participants),
            "scheduled_at": self.scheduled_at.isoformat(),
            "status": self.status,
            "outcome": self.outcome,
            "score": self.score,
            "provenance": self.provenance,
            "license": self.license,
            "retrieved_at": self.retrieved_at.isoformat(),
            "observed_source_timestamp": (
                self.observed_source_timestamp.isoformat()
                if self.observed_source_timestamp else None),
            "timezone_verified": self.timezone_verified,
            "sport_specific": dict(self.sport_specific),
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
