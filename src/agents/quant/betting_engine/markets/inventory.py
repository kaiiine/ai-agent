"""L'inventaire assemblé : observation -> famille -> capacité, une ligne par marché.

Ce module ne décide rien et n'évalue rien. Il répond à une seule question, celle
qui doit précéder toute recommandation :

    « Qu'est-ce que le bookmaker propose, sport par sport, compétition par
      compétition, événement par événement, marché par marché, sélection par
      sélection — et que savons-nous en faire ? »

DEUX AXES QUI NE SE MÉLANGENT JAMAIS. Un marché a un statut de LECTURE
(`OBSERVED` / `CANONICALIZED` / `AMBIGUOUS`) et un statut de CAPACITÉ
(`MODEL_AVAILABLE` / `MODEL_NOT_AVAILABLE` / `DATA_NOT_AVAILABLE` /
`UNSUPPORTED`). Les confondre produit la faute que tout l'ordre observer →
canonicaliser → vérifier → modéliser sert à empêcher : prendre la compréhension
d'un marché pour la capacité à le prédire.

LES DÉNOMINATEURS SONT CEUX DU CATALOGUE. Un taux de couverture calculé sur les
marchés parvenus jusqu'au modèle vaudrait toujours 100 %. `MarketCoverage` compte
donc à partir de ce qui a été OBSERVÉ, et distingue une absence de mesure
(`None`) d'une mesure nulle (`0`) — un sport non parcouru n'a pas 0 % de
couverture, il n'en a pas.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .capability import CapabilityResolution, CapabilityStatus, resolve_model
from .families import ClassificationStatus, MarketClassification, MarketFamily, classify
from .observation import RawMarketObservation

#: Ce que le rendu doit écrire quand rien n'a été mesuré. Jamais `0`, jamais `—`.
NOT_MEASURED = "NOT_MEASURED"


@dataclass(frozen=True)
class InventoryRow:
    """Un marché, de bout en bout : ce qu'il est, ce qu'on en comprend, ce qu'on
    peut en faire. L'observation d'origine reste attachée — une ligne d'inventaire
    doit pouvoir être rejouée sans retourner au réseau."""

    observation: RawMarketObservation
    classification: MarketClassification
    capability: CapabilityResolution

    @property
    def sport(self) -> str:
        return self.observation.sport

    @property
    def family(self) -> MarketFamily:
        return self.classification.family

    @property
    def evaluable(self) -> bool:
        """Un modèle validé couvre ce marché ET son contexte. Ne dit RIEN de
        l'opportunité : ni cote, ni EV, ni recommandation n'entrent ici."""
        return self.capability.status is CapabilityStatus.MODEL_AVAILABLE

    def describe(self) -> str:
        return (f"{self.classification.describe()} · {self.capability.status.value}"
                f" · {self.observation.nb_selections} sélection(s)")


def build_row(obs: RawMarketObservation) -> InventoryRow:
    """Une observation -> une ligne d'inventaire complète.

    L'ordre est imposé et non commutatif : on ne demande jamais au registre de
    capacité ce qu'il pense d'un marché dont la famille n'est pas établie. Sans
    cela, une résolution optimiste pourrait attribuer un modèle à un marché mal
    lu — exactement le chemin « voir une cote, inventer une probabilité ».
    """
    classification = classify(obs)
    capacite = resolve_model(
        winamax_sport_id=obs.sport_id,
        family=classification.family,
        # Le contexte porte les paramètres ET l'identifiant de famille de la
        # source : deux marchés de même famille canonique et de mêmes paramètres
        # peuvent avoir des sujets différents que seul cet identifiant sépare.
        context={**classification.parameters,
                 "source_family_id": classification.source_family_id})
    return InventoryRow(obs, classification, capacite)


def build_inventory(observations) -> tuple[InventoryRow, ...]:
    return tuple(build_row(o) for o in observations)


@dataclass(frozen=True)
class MarketCoverage:
    """La couverture marché d'un parcours, avec ses dénominateurs.

    Chaque compteur porte la population qu'il décrit. `events` compte des
    ÉVÉNEMENTS, `markets` des MARCHÉS, `selections` des SÉLECTIONS : trois
    populations distinctes qu'un seul « scannés » confondait.
    """

    events: int = 0
    markets: int = 0
    selections: int = 0
    canonicalized: int = 0
    unmapped: int = 0
    ambiguous: int = 0
    model_available: int = 0
    model_not_available: int = 0
    unsupported: int = 0
    data_not_available: int = 0
    by_family: dict[str, int] = field(default_factory=dict)
    by_sport: dict[str, dict] = field(default_factory=dict)
    #: sport -> panne, et famille -> panne. Une branche en panne n'est pas une
    #: branche vide (cf. isolation du scan).
    errors_by_sport: dict[str, str] = field(default_factory=dict)
    errors_by_family: dict[str, str] = field(default_factory=dict)
    #: Marchés dont un paramètre inconnu est apparu : le signal qu'une source a
    #: changé sous nos pieds.
    unknown_parameters: dict[str, int] = field(default_factory=dict)

    def _ratio(self, numerateur: int) -> float | str:
        """Un taux n'existe qu'avec un dénominateur observé."""
        if not self.markets:
            return NOT_MEASURED
        return round(numerateur / self.markets, 4)

    @property
    def canonicalization_rate(self) -> float | str:
        return self._ratio(self.canonicalized)

    @property
    def model_coverage_rate(self) -> float | str:
        return self._ratio(self.model_available)

    def counters_balance(self) -> tuple[bool, str]:
        """Les statuts de lecture partitionnent-ils réellement les marchés ?

        Un compteur qui ne boucle pas signale un marché tombé entre deux
        catégories — c'est-à-dire un marché perdu, ce que cet inventaire existe
        précisément pour empêcher.
        """
        somme = self.canonicalized + self.unmapped + self.ambiguous
        if somme == self.markets:
            return True, f"{self.canonicalized} + {self.unmapped} + {self.ambiguous} = {self.markets}"
        return False, (f"lecture : {somme} ≠ {self.markets} marchés observés "
                       f"({self.markets - somme} non classé(s))")


def measure(rows, *, errors_by_sport=None, errors_by_family=None) -> MarketCoverage:
    """Agrège les lignes d'inventaire. N'invente aucun compteur : tout ce qui est
    rendu ici se recompte à partir des lignes fournies."""
    lignes = list(rows)
    familles: Counter = Counter()
    par_sport: dict[str, Counter] = {}
    inconnus: Counter = Counter()
    evenements: set[tuple] = set()
    statuts_lecture: Counter = Counter()
    statuts_capacite: Counter = Counter()
    selections = 0

    for ligne in lignes:
        obs = ligne.observation
        evenements.add((obs.sport_id, obs.source_event_id))
        selections += obs.nb_selections
        familles[ligne.family.value] += 1
        statuts_lecture[ligne.classification.status] += 1
        statuts_capacite[ligne.capability.status] += 1
        for cle in obs.cles_inconnues:
            inconnus[cle] += 1

        compte = par_sport.setdefault(obs.sport, Counter())
        compte["markets"] += 1
        compte["selections"] += obs.nb_selections
        compte[ligne.family.value] += 1
        compte[ligne.capability.status.value] += 1
        if ligne.classification.canonical:
            compte["canonicalized"] += 1

    return MarketCoverage(
        events=len(evenements),
        markets=len(lignes),
        selections=selections,
        canonicalized=statuts_lecture[ClassificationStatus.CANONICALIZED],
        unmapped=statuts_lecture[ClassificationStatus.OBSERVED],
        ambiguous=statuts_lecture[ClassificationStatus.AMBIGUOUS],
        model_available=statuts_capacite[CapabilityStatus.MODEL_AVAILABLE],
        model_not_available=statuts_capacite[CapabilityStatus.MODEL_NOT_AVAILABLE],
        unsupported=statuts_capacite[CapabilityStatus.UNSUPPORTED],
        data_not_available=statuts_capacite[CapabilityStatus.DATA_NOT_AVAILABLE],
        by_family=dict(familles.most_common()),
        by_sport={s: dict(c) for s, c in sorted(par_sport.items())},
        errors_by_sport=dict(errors_by_sport or {}),
        errors_by_family=dict(errors_by_family or {}),
        unknown_parameters=dict(inconnus.most_common()),
    )
