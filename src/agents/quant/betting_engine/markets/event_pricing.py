"""TOUS les marchés d'un événement, de l'observation au candidat comparable.

C'est la pièce qui manquait entre l'inventaire et le produit. Les composants
existaient tous — lecture, canonicalisation, capacité, liaison des sélections,
pricing, fraîcheur, dévigorisation, espérance settlement-aware — mais aucun
chemin ne les enchaînait sur un vrai événement : seul le banc de mesure le
faisait, et une propriété prouvée dans un harness n'est pas une propriété du
produit.

L'ORDRE EST IMPOSÉ ET NON COMMUTATIF :

    observer -> canonicaliser -> vérifier la capacité -> lier les sélections
    -> modéliser -> dévigoriser sur le marché COMPLET -> espérance
    -> fraîcheur MESURÉE -> comparer

Chaque étape peut refuser, et chaque refus est COMPTÉ sous son motif. La somme
des compteurs égale le nombre de marchés vus : un marché qui disparaît sans
motif est un bug, pas un silence.

UNE SEULE DISTRIBUTION PAR ÉVÉNEMENT. Les neuf marchés football priceables d'une
rencontre sont neuf lectures de la MÊME loi jointe. Les calculer neuf fois
coûterait neuf fois plus cher et — bien pire — ne garantirait plus qu'ils soient
cohérents entre eux. Le mémo par événement est donc une propriété de correction
autant que de performance, et `probability_origin` en porte la trace jusqu'au
sizing.

CE MODULE NE DÉCIDE RIEN. Il ne classe pas, ne mise pas, ne promeut aucune
maturité. Il produit des candidats et les motifs de ceux qui n'en sont pas.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from .capability import CapabilityStatus
from .families import MarketFamily
from .inventory import InventoryRow, build_row
from .observation import observation_de_marche
from .pricing import MarketPricing, PricingStatus, avec_fraicheur, price_market
from .review_ranking import ReviewCandidate
from .selection_binding import canonicaliser_selections

#: Motifs d'exclusion, nommés une fois. Un motif est une donnée de sortie : il
#: est affiché, compté et testé, donc il ne doit pas vivre dans une f-string.
RULE_UNKNOWN = "RULE_UNKNOWN"                          # famille non démontrée
SELECTION_FAILED = "SELECTION_CANONICALIZATION_FAILED"
NO_ODDS = "NO_ODDS"                                    # marché suspendu : aucune cote
NO_PRICER = "NO_PRICER_FOR_SPORT"


@dataclass(frozen=True)
class PricedMarket:
    """Un marché d'un événement, lu jusqu'au bout — ou refusé avec son motif."""

    row: InventoryRow
    pricing: MarketPricing
    #: sélection canonique -> cote observée. Vide quand le marché est suspendu.
    odds: dict = field(default_factory=dict)

    @property
    def priced(self) -> bool:
        return self.pricing.status is PricingStatus.PRICED

    @property
    def family(self) -> MarketFamily:
        return self.row.family

    def describe(self) -> str:
        return f"{self.row.classification.describe()} · {self.pricing.status.value}"


@dataclass
class MarketFunnel:
    """L'entonnoir du run, avec ses dénominateurs (§7).

    Chaque compteur nomme la population qu'il décrit. Un taux n'est rendu que si
    son dénominateur a été RÉELLEMENT mesuré : `None` n'est pas `0`.
    """

    events_seen: int = 0
    events_priced: int = 0
    markets_observed: int = 0
    markets_canonicalized: int = 0
    markets_capability_available: int = 0
    markets_priced: int = 0
    markets_with_probability_low: int = 0
    markets_freshness_measurable: int = 0
    selections_priced: int = 0
    #: motif -> nombre de marchés écartés. La somme des motifs + `markets_priced`
    #: doit valoir `markets_observed`.
    exclusions: Counter = field(default_factory=Counter)

    def exclure(self, motif: str) -> None:
        self.exclusions[motif] += 1

    def equilibre(self) -> tuple[bool, str]:
        somme = self.markets_priced + sum(self.exclusions.values())
        if somme == self.markets_observed:
            return True, f"{somme} == {self.markets_observed}"
        return False, (f"{somme} ≠ {self.markets_observed} marchés observés — "
                       f"{self.markets_observed - somme} sans motif")

    def principaux_motifs(self, n: int = 8) -> list[tuple[str, int]]:
        return self.exclusions.most_common(n)


class _DistributionPartagee:
    """Mémorise la distribution d'un événement pour toute sa grappe de marchés.

    Enveloppe le modèle de base plutôt que le pricer : le pricer reste ignorant
    du fait qu'il est appelé neuf fois, et rien de sa logique n'est dupliqué.
    """

    def __init__(self, base):
        self._base = base
        self._cache: dict = {}
        self.appels = 0

    def __getattr__(self, nom):
        return getattr(self._base, nom)

    def distribution(self, event, features, point_in_time):
        cle = (getattr(event, "event_id", None), point_in_time)
        if cle not in self._cache:
            self.appels += 1
            self._cache[cle] = self._base.distribution(event, features, point_in_time)
        return self._cache[cle]


def pricers_partages(pricers):
    """Des pricers dont la distribution est calculée une fois par événement."""
    partages = []
    for pricer in pricers:
        base = getattr(pricer, "_base", None)
        if base is not None and hasattr(base, "distribution"):
            pricer = type(pricer)(base=_DistributionPartagee(base))
        partages.append(pricer)
    return tuple(partages)


def price_event_markets(
    raw_event, *, event, features, decision_time: datetime, pricers,
    roles, competition_id: str | None = None, funnel: MarketFunnel | None = None,
    freshness_at: datetime | None = None,
) -> list[PricedMarket]:
    """Tous les marchés d'UN événement déjà scanné. Aucun appel réseau ici.

    `event`/`features` viennent du chemin d'évaluation existant : ce module ne
    reconstruit ni l'un ni l'autre, sans quoi deux versions des mêmes features
    pourraient coexister dans le même run.

    `freshness_at` est l'instant AUQUEL ON MESURE L'ÂGE d'une cote, et il n'est
    pas `decision_time`. Le point-in-time du modèle est capturé AVANT le scan —
    c'est ce qui garantit l'absence de fuite — donc les cotes lui sont
    POSTÉRIEURES, et leur âge y est négatif. Mesuré : la fraîcheur de 262
    sélections réelles rendait `UNKNOWN` sur cette seule inversion, et tous les
    candidats devenaient non comparables. Les deux instants sont légitimes et
    différents ; les confondre rendait la mesure impossible. `None` = pas de
    référence fournie, donc aucune fraîcheur attachée — jamais une fraîcheur
    supposée.
    """
    funnel = funnel if funnel is not None else MarketFunnel()
    funnel.events_seen += 1
    resultats: list[PricedMarket] = []
    price_pour_evenement = 0

    for raw_market in raw_event.markets:
        funnel.markets_observed += 1
        obs = observation_de_marche(raw_event, raw_market, competition=competition_id)
        ligne = build_row(obs)

        if not ligne.classification.canonical:
            funnel.exclure(RULE_UNKNOWN)
            continue
        funnel.markets_canonicalized += 1

        statut = ligne.capability.status
        if statut is not CapabilityStatus.MODEL_AVAILABLE:
            funnel.exclure(statut.value)
            continue
        funnel.markets_capability_available += 1

        binding = canonicaliser_selections(
            family=ligne.family, codes=[s.code for s in obs.selections], roles=roles,
            parameters=ligne.classification.parameters)
        if not binding.complete:
            funnel.exclure(SELECTION_FAILED)
            continue

        cotes = {binding.par_code[s.code]: s.decimal_odds
                 for s in obs.selections
                 if s.decimal_odds and s.decimal_odds > 1.0 and s.code in binding.par_code}
        if not cotes:
            funnel.exclure(NO_ODDS)
            continue

        parametres = dict(ligne.classification.parameters)
        parametres["source_family_id"] = ligne.classification.source_family_id
        prix = price_market(
            event=event, sport=obs.sport, family=ligne.family, parameters=parametres,
            context={"features": features, "point_in_time": decision_time,
                     # Les rôles : un total d'ÉQUIPE cote un camp, et le camp ne
                     # devient « domicile » ou « extérieur » que par le résolveur.
                     "roles": roles,
                     # Le support du marché vient du MARCHÉ, jamais d'une grille
                     # supposée : un score exact n'offre pas 5:5.
                     "offered_selections": tuple(binding.par_code[s.code]
                                                 for s in obs.selections
                                                 if s.code in binding.par_code)},
            pricers=pricers)

        if prix.status is not PricingStatus.PRICED:
            funnel.exclure(prix.status.value)
            resultats.append(PricedMarket(ligne, prix, {}))
            continue

        prix = prix.with_market_odds(cotes)
        if freshness_at is not None:
            prix = avec_fraicheur(prix, obs.observed_at, freshness_at)

        funnel.markets_priced += 1
        funnel.selections_priced += len(prix.selections)
        if any(s.probability_low is not None for s in prix.selections):
            funnel.markets_with_probability_low += 1
        if prix.freshness is not None:
            funnel.markets_freshness_measurable += 1
        price_pour_evenement += 1
        resultats.append(PricedMarket(ligne, prix, cotes))

    if price_pour_evenement:
        funnel.events_priced += 1
    return resultats


def review_candidates(
    marches, *, sport: str, competition: str | None = None,
    event_label: str | None = None,
) -> list[ReviewCandidate]:
    """Marchés pricés -> candidats comparables, une entrée par SÉLECTION.

    Les marchés non pricés ne produisent AUCUN candidat : une abstention n'est
    pas une opportunité mal classée, c'est l'absence d'opportunité. Leur motif
    vit dans l'entonnoir, pas dans le classement.
    """
    candidats: list[ReviewCandidate] = []
    for marche in marches:
        if not marche.priced:
            continue
        prix = marche.pricing
        obs = marche.row.observation
        for selection in prix.selections:
            candidats.append(ReviewCandidate(
                source_event_id=obs.source_event_id,
                sport=sport,
                competition=competition or obs.competition,
                family=prix.family,
                parameters=dict(prix.parameters),
                context=dict(prix.context),
                selection=selection.selection,
                bookmaker_odds=selection.bookmaker_odds,
                implied_probability=selection.implied_probability,
                vig_adjusted_probability=selection.vig_adjusted_probability,
                fair_probability=selection.fair_probability,
                probability_low=selection.probability_low,
                expected_value=selection.expected_value,
                maturity=prix.maturity,
                freshness=prix.freshness,
                data_quality=prix.data_quality,
                probability_origin=prix.probability_origin,
                settlement_shares=selection.settlement_shares,
                event_label=event_label or obs.event_label,
                market_source_id=obs.market_source_id,
                observed_at=obs.observed_at,
                abstention_reasons=prix.abstention_reasons,
                bet_type=obs.bet_type,
                bet_type_name=obs.bet_type_name,
                model_name=prix.model_name,
                model_version=prix.model_version,
                bookmaker=obs.bookmaker,
            ))
    return candidats
