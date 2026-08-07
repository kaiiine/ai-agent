"""`InternetFeature` — ce qu'Internet a le droit de devenir, et rien d'autre.

Une recherche web ne produit jamais une probabilité. Elle produit un FAIT DATÉ ET
SOURCÉ, que le modèle exploitera peut-être un jour — ou pas.

La distinction n'est pas rhétorique. Une blessure annoncée par l'ATP est une
information réelle et utile à lire ; la transformer en ajustement de probabilité
demanderait de savoir DE COMBIEN, ce qu'aucune page web ne dit. Entre les deux il
n'y a pas un petit pas mais un modèle entier, avec sa validation walk-forward.

Tant que ce modèle n'existe pas, la feature reste INFORMATIVE : affichée à
l'utilisateur, jamais injectée dans le calcul.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

#: Ce qu'une recherche peut établir. Fermé volontairement : un type non prévu
#: doit être ajouté ici consciemment, pas apparaître par accident.
FEATURE_TYPES = frozenset({
    "INJURY", "WITHDRAWAL", "SUSPENSION", "LINEUP", "WEATHER", "SURFACE",
    "VENUE_CHANGE", "SCHEDULE_CHANGE", "OFFICIAL_RANKING", "DRAW", "H2H",
    "REST_STATUS", "POSTPONEMENT",
})

#: Statut d'exploitation. `INFORMATIVE` est le SEUL état atteignable aujourd'hui :
#: aucun modèle ne consomme de feature Internet. `QUANTITATIVE` existe pour que le
#: jour où l'un le fera, ce soit une décision visible dans un diff.
INFORMATIVE = "INFORMATIVE"
QUANTITATIVE = "QUANTITATIVE"


@dataclass(frozen=True)
class InternetFeature:
    """Un fait externe, daté, sourcé, et non quantifié."""

    feature_type: str
    value: str
    source: str
    url: str
    retrieved_at: datetime
    confidence: str = "UNVERIFIED"      # OFFICIAL | REPUTABLE | UNVERIFIED
    usage: str = INFORMATIVE
    subject: str | None = None          # participant ou événement concerné

    def __post_init__(self) -> None:
        if self.feature_type not in FEATURE_TYPES:
            raise ValueError(f"type de feature hors contrat : {self.feature_type!r}")
        if self.usage != INFORMATIVE:
            # Verrou explicite. Le jour où un modèle exploitera une feature
            # Internet, ce sera par une modification consciente de cette ligne,
            # accompagnée de sa validation — pas par un champ passé en douce.
            raise ValueError(
                "aucune feature Internet n'est exploitable quantitativement : "
                "il faudrait un modèle validé, pas un champ")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at doit être timezone-aware")

    def describe(self) -> str:
        marque = {"OFFICIAL": "source officielle",
                  "REPUTABLE": "source reconnue"}.get(self.confidence, "source non vérifiée")
        sujet = f"{self.subject} — " if self.subject else ""
        return (f"{sujet}{self.value} ({self.feature_type}, {marque} : {self.source}, "
                f"{self.retrieved_at:%d/%m %H:%M})")


def make(
    feature_type: str, value: str, *, source: str, url: str,
    confidence: str = "UNVERIFIED", subject: str | None = None,
    retrieved_at: datetime | None = None,
) -> InternetFeature:
    return InternetFeature(
        feature_type=feature_type, value=value, source=source, url=url,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        confidence=confidence, subject=subject)
