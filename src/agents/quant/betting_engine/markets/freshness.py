"""Fraîcheur d'un marché — à la granularité que la SOURCE fournit, pas plus fine.

MESURE, PAS SUPPOSITION. Un `PRELOADED_STATE` Winamax a été inspecté champ par
champ, aux quatre niveaux où un horodatage pourrait vivre :

    état (snapshot)   aucune clé temporelle
    match             aucune (matchStart est l'heure du COUP D'ENVOI, pas de la cote)
    bet (marché)      aucune
    outcome (cote)    `odds[id]` est un flottant nu — 1.35, sans métadonnée

Le bookmaker ne date donc rien. Le seul instant honnête est celui où NOUS avons
récupéré la page, et il est le même pour tous les marchés de tous les événements
d'un même appel. La granularité réelle est SNAPSHOT, et prétendre plus fin —
« cette cote-ci date de 12:03:41 » — serait une donnée inventée.

CONSÉQUENCE POUR LA MATURITÉ. `measurable_live_freshness` ne peut pas être auto-
déclaré par une capacité : ce module rend ce qu'il a MESURÉ, y compris `UNKNOWN`,
et ne remplace jamais une absence par une valeur favorable. `UNKNOWN` n'est pas
`STALE` non plus : l'un dit « je ne sais pas », l'autre « je sais, et c'est
vieux ». Le premier interdit la mise faute de mesure, le second faute de
fraîcheur — deux rapports différents, deux réparations différentes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class FreshnessGranularity(str, Enum):
    """À quel niveau la SOURCE date ses cotes."""

    SNAPSHOT = "SNAPSHOT"        # un instant pour toute la récupération
    MARKET = "MARKET"            # un instant par marché
    SELECTION = "SELECTION"      # un instant par sélection
    NONE = "NONE"                # la source ne date rien du tout


class FreshnessStatus(str, Enum):
    MEASURABLE = "MEASURABLE"
    UNKNOWN = "UNKNOWN"          # pas d'instant d'observation : rien à mesurer
    STALE = "STALE"              # mesuré, et au-delà du délai admis


#: Ce que Winamax fournit, mesuré. `NONE` côté source : aucun champ temporel dans
#: le payload. L'instant d'observation vient de notre propre récupération, donc
#: la granularité EFFECTIVE est le snapshot.
GRANULARITE_SOURCE_WINAMAX = FreshnessGranularity.NONE
GRANULARITE_EFFECTIVE_WINAMAX = FreshnessGranularity.SNAPSHOT

#: Au-delà, la cote observée ne décrit plus le marché au moment de décider. Ce
#: n'est pas un seuil de décision money (ni EV, ni Kelly, ni maturité) : c'est la
#: limite au-delà de laquelle la mesure elle-même cesse d'être une mesure.
AGE_MAX = timedelta(minutes=15)


@dataclass(frozen=True)
class MarketFreshness:
    """La fraîcheur d'un marché, avec sa provenance temporelle."""

    status: FreshnessStatus
    granularity: FreshnessGranularity
    observed_at: datetime | None = None
    decision_at: datetime | None = None
    age_seconds: float | None = None
    #: `None` quand `UNKNOWN` : un score de fraîcheur absent n'est pas 0. Zéro
    #: serait une mesure — la pire, celle qui dit « parfaitement périmé ».
    score: float | None = None
    reason: str = ""

    @property
    def measurable(self) -> bool:
        return self.status is FreshnessStatus.MEASURABLE


def evaluer(observed_at: datetime | None, decision_at: datetime | None, *,
            granularity: FreshnessGranularity = GRANULARITE_EFFECTIVE_WINAMAX,
            age_max: timedelta = AGE_MAX) -> MarketFreshness:
    """Fraîcheur d'une observation, ou l'explication de son absence.

    Le score décroît linéairement de 1 (à l'instant même) à 0 (à `age_max`). Une
    observation POSTÉRIEURE à la décision n'est pas « très fraîche » : c'est une
    incohérence, et elle rend `UNKNOWN` plutôt qu'un score flatteur.
    """
    if observed_at is None or decision_at is None:
        return MarketFreshness(
            FreshnessStatus.UNKNOWN, granularity, observed_at, decision_at,
            reason="aucun instant d'observation : la source ne date pas ses cotes "
                   "et la récupération n'a pas été horodatée")

    age = (decision_at - observed_at).total_seconds()
    if age < 0:
        return MarketFreshness(
            FreshnessStatus.UNKNOWN, granularity, observed_at, decision_at, age_seconds=age,
            reason=f"observation postérieure à la décision de {-age:.0f} s — "
                   "incohérence d'horodatage, pas une fraîcheur")

    if age > age_max.total_seconds():
        return MarketFreshness(
            FreshnessStatus.STALE, granularity, observed_at, decision_at, age_seconds=age,
            score=0.0,
            reason=f"cote observée il y a {age / 60:.1f} min, au-delà de "
                   f"{age_max.total_seconds() / 60:.0f} min")

    return MarketFreshness(
        FreshnessStatus.MEASURABLE, granularity, observed_at, decision_at, age_seconds=age,
        score=round(1.0 - age / age_max.total_seconds(), 6),
        reason=f"observée il y a {age:.0f} s (granularité {granularity.value})")


def partagee_par_evenement(observations) -> bool:
    """Tous ces marchés viennent-ils du MÊME instant d'observation ?

    Si oui — et c'est le cas d'une page Winamax, qui livre tous les marchés d'un
    événement en une réponse — la fraîcheur se mesure UNE fois et se partage.
    Sinon, chaque marché garde la sienne : on ne moyenne pas des instants.
    """
    instants = {o.observed_at for o in observations}
    return len(instants) == 1 and None not in instants
