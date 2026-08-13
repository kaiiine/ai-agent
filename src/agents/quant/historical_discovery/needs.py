"""Ce qui MANQUE au modèle, exprimé avant de savoir où le chercher.

Le réflexe naturel est de partir des sources : « quelles ligues peut-on
ajouter ? ». Il produit des données qu'aucun modèle n'attendait, et laisse
intacts les trous qui coûtent réellement des prédictions. La question utile est
l'inverse : « quelle observation historique me manque pour évaluer cette
rencontre ? ».

Un `HistoricalDataNeed` est donc formulé PAR LE MODÈLE, depuis une exclusion
mesurée — jamais depuis un catalogue de providers. Il porte sa propre raison
d'exister, ce qui le rend vérifiable : quand la donnée arrive, on peut dire si
le besoin est comblé, et sinon de combien.

SPORT-AGNOSTIC. Le noyau ne connaît ni buts, ni sets, ni manches : une entité a
besoin d'observations antérieures à une date. Football, tennis et baseball
diffèrent dans ce qu'est une observation, pas dans le fait d'en manquer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

#: Types d'entité reconnus. Un besoin porte sur ce qui a un historique propre.
ENTITY_TYPES = frozenset({"team", "player", "competition"})

#: Nature de l'observation manquante. Distinguer permet de ne pas confondre
#: « je n'ai pas ses matchs » et « je n'ai pas son classement ».
DATA_TYPES = frozenset({"matches", "results", "rankings", "lineups", "odds"})


@dataclass(frozen=True)
class HistoricalDataNeed:
    """Une preuve historique absente, et ce qu'il faudrait pour la combler.

    `minimum_required_evidence` n'est pas indicatif : c'est le critère de
    clôture. Sans lui, un backfill « améliore » sans jamais finir, et rien ne
    dit si l'effort suivant sert encore à quelque chose.
    """

    sport: str
    entity_type: str
    entity_ids: tuple[str, ...]
    data_type: str
    reason: str                          # code d'exclusion mesuré, pas une intuition
    minimum_required_evidence: int       # nb d'observations antérieures requises
    competition_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None      # borne HAUTE : rien après la prédiction (§9)
    observed_evidence: int = 0           # ce qu'on a déjà, pour mesurer l'écart
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entity_type not in ENTITY_TYPES:
            raise ValueError(f"entity_type inconnu : {self.entity_type!r}")
        if self.data_type not in DATA_TYPES:
            raise ValueError(f"data_type inconnu : {self.data_type!r}")
        if not self.entity_ids:
            raise ValueError("un besoin sans entité ne se comble pas")
        if self.minimum_required_evidence < 0:
            raise ValueError("minimum_required_evidence négatif")

    @property
    def gap(self) -> int:
        """Combien d'observations manquent encore. Zéro = besoin comblé."""
        return max(0, self.minimum_required_evidence - self.observed_evidence)

    @property
    def is_satisfied(self) -> bool:
        return self.gap == 0

    @property
    def entities_affected(self) -> int:
        return len(self.entity_ids)

    def as_dict(self) -> dict:
        return {
            "sport": self.sport,
            "entity_type": self.entity_type,
            "entity_ids": list(self.entity_ids),
            "data_type": self.data_type,
            "reason": self.reason,
            "minimum_required_evidence": self.minimum_required_evidence,
            "observed_evidence": self.observed_evidence,
            "gap": self.gap,
            "competition_id": self.competition_id,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "entities_affected": self.entities_affected,
            "detail": dict(self.detail),
        }
