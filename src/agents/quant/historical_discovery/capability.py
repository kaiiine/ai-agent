"""Ce qu'un provider DÉCLARE savoir servir en historique.

Le registre de couverture existant (`provider_coverage_registry`) répond à une
question voisine mais différente : « ce provider couvre-t-il CETTE compétition,
CETTE saison ? ». Il faut une ligne par compétition et par saison, vérifiée une
à une — c'est la bonne granularité pour servir une rencontre, et la mauvaise
pour DÉCOUVRIR où chercher un historique qu'on n'a pas encore.

D'où une déclaration par (provider, sport) : profondeur historique, types
d'entités, natures de données. Elle sert à ÉLIMINER — inutile d'interroger une
source qui ne remonte pas assez loin — jamais à affirmer une couverture. La
preuve reste la vérification par compétition, en aval.

NE PAS CODER EN DUR UN CATALOGUE DE COMPÉTITIONS. `competitions` accepte le
joker `("*",)` : une archive publique qui couvre tout un pays n'a pas à voir sa
liste recopiée ici, où elle deviendrait fausse à la saison suivante.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .classification import SourceClassification

#: Ce qu'une source peut porter. Aligné sur `DATA_TYPES` des besoins : un besoin
#: qu'aucune capacité ne nomme est un besoin qu'on ne saurait pas router.
DATA_KINDS = frozenset({"results", "scores", "timestamps", "lineups",
                        "rankings", "odds"})

ACCESS_TYPES = frozenset({"OPEN", "API_KEY", "PAID", "SCRAPE"})


@dataclass(frozen=True)
class HistoricalProviderCapability:
    """Déclaration de capacité historique, adossée à une classification.

    La classification n'est pas décorative : une capacité magnifique dont la
    source est `NOT_USABLE` ne doit jamais être routée. `is_routable` fond les
    deux, pour qu'aucun appelant n'ait à penser à vérifier les deux.
    """

    provider: str
    sport: str
    competitions: tuple[str, ...]        # ("*",) = tout le sport, sans liste figée
    historical_depth_years: int | None   # None = inconnu, jamais « illimité » par défaut
    entity_types: tuple[str, ...]
    data_kinds: tuple[str, ...]
    access_type: str
    classification: SourceClassification
    rate_limit_per_min: int | None = None
    earliest_season: str | None = None
    latest_season: str | None = None
    provenance_quality: str = "UNKNOWN"  # OFFICIAL | DERIVED | COMMUNITY | UNKNOWN
    notes: str = ""
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.access_type not in ACCESS_TYPES:
            raise ValueError(f"access_type inconnu : {self.access_type!r}")
        inconnus = set(self.data_kinds) - DATA_KINDS
        if inconnus:
            raise ValueError(f"data_kinds inconnus : {sorted(inconnus)}")

    @property
    def is_routable(self) -> bool:
        """Servir une capacité dont la source est inutilisable serait une fuite
        de licence déguisée en détail de routage."""
        return self.classification.is_usable

    def couvre_competition(self, competition_id: str) -> bool:
        return "*" in self.competitions or competition_id in self.competitions

    def peut_repondre(self, need) -> bool:
        """Filtre de ROUTAGE, pas une promesse : la source pourrait contenir ce
        besoin. Seule la récupération réelle le prouvera."""
        if not self.is_routable:
            return False
        if need.sport != self.sport:
            return False
        if need.entity_type not in self.entity_types:
            return False
        if need.competition_id and not self.couvre_competition(need.competition_id):
            return False
        return True

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "sport": self.sport,
            "competitions": list(self.competitions),
            "historical_depth_years": self.historical_depth_years,
            "earliest_season": self.earliest_season,
            "latest_season": self.latest_season,
            "entity_types": list(self.entity_types),
            "data_kinds": list(self.data_kinds),
            "access_type": self.access_type,
            "rate_limit_per_min": self.rate_limit_per_min,
            "provenance_quality": self.provenance_quality,
            "routable": self.is_routable,
            "classification": self.classification.as_dict(),
            "notes": self.notes,
        }


class CapabilityRegistry:
    """Les capacités connues, interrogeables par besoin.

    Volontairement en mémoire et alimenté par du code : une capacité est une
    AFFIRMATION VÉRIFIÉE, elle se relit et se discute en revue. Un fichier de
    configuration éditable rendrait trop simple d'ajouter une source dont
    personne n'a lu la licence.
    """

    def __init__(self, capabilities=()):
        self._caps: list[HistoricalProviderCapability] = list(capabilities)

    def register(self, cap: HistoricalProviderCapability) -> None:
        self._caps.append(cap)

    def all(self) -> tuple[HistoricalProviderCapability, ...]:
        return tuple(self._caps)

    def for_sport(self, sport: str) -> tuple[HistoricalProviderCapability, ...]:
        return tuple(c for c in self._caps if c.sport == sport)

    def candidates(self, need) -> tuple[HistoricalProviderCapability, ...]:
        """Sources routables pour ce besoin, les plus profondes d'abord —
        une archive courte ne comblera pas un cold-start ancien."""
        eligibles = [c for c in self._caps if c.peut_repondre(need)]
        return tuple(sorted(
            eligibles, key=lambda c: (-(c.historical_depth_years or 0), c.provider)))

    def blocked(self, sport: str | None = None) -> tuple[HistoricalProviderCapability, ...]:
        """Capacités RÉELLES mais non routables — l'inventaire de ce qui bloque,
        qui serait invisible si on filtrait simplement les sources inutilisables."""
        return tuple(c for c in self._caps
                     if not c.is_routable and (sport is None or c.sport == sport))
