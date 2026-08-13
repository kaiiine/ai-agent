"""Quatrième étape : **pricer** — une structure comparable d'un sport à l'autre.

Le moteur de recommandation supposait partout `MATCH_WINNER`. Comparer un
moneyline tennis, un Plus/Moins football et un handicap basket demande un objet
commun ; sans lui, chaque famille traînerait son propre format et la comparaison
finirait par se faire sur le seul dénominateur partagé — la cote. C'est
exactement le chemin interdit : voir une cote, en déduire une opportunité.

CE QUE CE MODULE NE FAIT PAS, ET C'EST VOLONTAIRE :

- il ne redéfinit AUCUNE formule économique. L'espérance vient de
  `value_engine.expected_value.ev` — un second calcul, même identique le jour où
  on l'écrit, diverge tôt ou tard du premier ;
- il ne décide rien : pas de seuil, pas de mise, pas de sélection ;
- il n'invente jamais une probabilité. Un marché qu'aucun modèle ne couvre rend
  une abstention MOTIVÉE, pas une estimation par défaut.

L'ABSTENTION EST UN RÉSULTAT DE PREMIÈRE CLASSE. Une famille sans modèle, une
donnée manquante, une règle de règlement indémontrable : chacun produit un
`MarketPricing` porteur de son motif. Rien ne disparaît en silence, et rien ne se
faufile dans un classement sans probabilité défendable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum

from .families import MarketFamily


class PricingStatus(str, Enum):
    PRICED = "PRICED"                            # probabilité défendable produite
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"  # aucun modèle pour (sport, famille, contexte)
    DATA_NOT_AVAILABLE = "DATA_NOT_AVAILABLE"    # modèle présent, données absentes pour CET événement
    RULE_NOT_DEMONSTRATED = "RULE_NOT_DEMONSTRATED"  # règle de règlement non démontrée
    #: Un modèle EXISTE et a été confronté à l'historique — il a échoué. C'est
    #: distinct de `MODEL_NOT_AVAILABLE`, qui dit « personne n'a essayé » : ici
    #: quelqu'un a essayé, et le résultat est un refus mesuré. Les confondre
    #: perdrait l'information la plus chère du chantier.
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    #: Un modèle couvre cette famille et ce sport, mais pas CETTE portée :
    #: mi-temps, période, équipe, joueur. Le nommer séparément dit quoi
    #: construire ; le confondre avec « pas de modèle » ferait croire qu'il n'y a
    #: rien, alors qu'il ne manque qu'une portée.
    MODEL_CONTEXT_MISMATCH = "MODEL_CONTEXT_MISMATCH"
    UNSUPPORTED = "UNSUPPORTED"                  # famille non canonicalisée


@dataclass(frozen=True)
class PricedSelection:
    """Une issue, chiffrée. Tout ce qu'il faut pour la comparer à une autre issue
    d'un autre sport — et tout ce qu'il faut pour refuser de la comparer."""

    selection: str
    model_probability: float
    #: `fair_probability` est la probabilité du modèle, dévigorisée d'aucune façon :
    #: dans AXON les deux termes désignent la même quantité (cf. `MarketPrediction`).
    #: Le champ est conservé pour que la structure parle le vocabulaire du domaine.
    fair_probability: float
    probability_low: float | None = None      # None = NON ESTIMÉ, jamais « zéro »
    probability_high: float | None = None
    bookmaker_odds: float | None = None
    #: 1/cote, marge du bookmaker COMPRISE. Ce n'est pas une probabilité de marché
    #: dévigorisée : la nommer ainsi ferait croire à une estimation concurrente.
    implied_probability: float | None = None
    edge: float | None = None                 # fair − vig_adjusted (cf. `with_odds`)
    expected_value: float | None = None       # value_engine, jamais recalculé ici
    #: Probabilité bookmaker DÉVIGORISÉE, calculée sur l'ensemble COHÉRENT des
    #: issues du marché. `implied_probability` seule (1/cote) contient la marge :
    #: comparée à une probabilité de modèle, elle fabrique un edge négatif
    #: artificiel de l'ordre de la marge — quelques points de pourcentage, soit
    #: l'ordre de grandeur de l'edge qu'on cherche.
    vig_adjusted_probability: float | None = None
    #: Somme des probabilités implicites du marché. 1,05 = 5 % de marge.
    market_overround: float | None = None
    #: Décomposition du règlement, quand le marché n'est pas WIN/LOSS pur.
    settlement_shares: tuple = ()

    def with_odds(self, decimal_odds: float | None,
                  *, no_vig: float | None = None,
                  overround: float | None = None) -> "PricedSelection":
        """Attache une cote et en dérive l'économie — via le moteur existant.

        `no_vig` vient du MARCHÉ entier (cf. `MarketPricing.with_market_odds`) :
        une sélection isolée ne permet pas de retirer la marge, et 1/cote n'est
        pas une probabilité bookmaker — c'est une probabilité gonflée de la marge.
        Quand elle est fournie, l'edge se calcule contre elle.

        L'espérance passe par la primitive settlement-aware si le marché déclare
        ses parts de règlement : sur un marché qui rembourse, la formule binaire
        surestime l'EV par unité misée d'un facteur 1/(1−P(push)).
        """
        if decimal_odds is None or decimal_odds <= 1.0:
            return self
        from ..value_engine.settlement import binary_shares
        from ..value_engine.settlement import expected_value as ev_settlement

        implied = 1.0 / decimal_odds
        reference = no_vig if no_vig is not None else implied
        parts = self.settlement_shares or binary_shares(self.fair_probability)
        return PricedSelection(
            selection=self.selection,
            model_probability=self.model_probability,
            fair_probability=self.fair_probability,
            probability_low=self.probability_low,
            probability_high=self.probability_high,
            bookmaker_odds=decimal_odds,
            implied_probability=implied,
            edge=self.fair_probability - reference,
            expected_value=ev_settlement(parts, decimal_odds),
            vig_adjusted_probability=no_vig,
            market_overround=overround,
            settlement_shares=self.settlement_shares,
        )


@dataclass(frozen=True)
class MarketPricing:
    """Le prix d'un marché entier : ses issues, sa provenance, ses réserves."""

    event_id: str
    sport: str
    family: MarketFamily
    parameters: Mapping = field(default_factory=dict)
    context: Mapping = field(default_factory=dict)
    status: PricingStatus = PricingStatus.UNSUPPORTED
    selections: tuple[PricedSelection, ...] = ()
    model_name: str | None = None
    model_version: str | None = None
    maturity: str | None = None                  # dérivée du ledger, jamais déclarée
    calibration_status: str | None = None
    data_quality: float | None = None
    freshness: float | None = None               # None = NON MESURÉE, jamais 0
    #: La fraîcheur COMPLÈTE : statut, granularité réellement fournie par la
    #: source, instant d'observation. Le score seul ne dit pas si l'absence vient
    #: d'un manque de mesure ou d'une cote périmée — et ces deux-là ne se
    #: réparent pas de la même façon.
    freshness_detail: object | None = None
    point_in_time: datetime | None = None
    abstention_reasons: tuple[str, ...] = ()
    #: De quelle distribution ces probabilités sortent. Deux marchés du même
    #: événement issus de la MÊME matrice sont corrélés par construction : sans
    #: cette trace, le sizing les traiterait comme indépendants (§10).
    probability_origin: str | None = None

    @property
    def priced(self) -> bool:
        return self.status is PricingStatus.PRICED

    @property
    def masse_attendue(self) -> float:
        """À combien somment les issues de CE marché quand la marge est retirée.

        Vaut 1 sur une partition — issues mutuellement exclusives et exhaustives :
        1X2, Plus/Moins, score exact avec son `other`. Vaut 2 sur une double
        chance : ses trois issues sont les unions deux à deux d'une partition à
        trois, donc chaque résultat y est couvert exactement deux fois.

        Ce n'est PAS une propriété du modèle, c'est la structure du marché. La
        confondre avec 1 aurait normalisé les cotes d'une double chance vers une
        somme de 1 et fabriqué un edge de −50 % sur chacune de ses issues.
        """
        return 2.0 if self.family is MarketFamily.DOUBLE_CHANCE else 1.0

    def with_market_odds(self, odds_par_selection: Mapping) -> "MarketPricing":
        """Attache les cotes du MARCHÉ ENTIER et dévigorise sur son ensemble cohérent.

        La marge ne se retire que sur un marché complet : « Plus de 2,5 » seul ne
        dit rien de la marge, « Plus + Moins » la donne exactement. Un marché
        incomplet (une seule issue cotée) garde donc `vig_adjusted_probability =
        None` — l'absence est déclarée, jamais comblée par 1/cote.
        """
        cotes = {nom: c for nom, c in odds_par_selection.items()
                 if c and c > 1.0 and any(s.selection == nom for s in self.selections)}
        complet = len(cotes) == len(self.selections) and len(self.selections) > 1

        sans_marge: dict = {}
        overround = None
        if complet:
            brutes = {nom: 1.0 / c for nom, c in cotes.items()}
            somme = sum(brutes.values())
            cible = self.masse_attendue
            overround = round(somme / cible, 6)
            if somme > 0:
                sans_marge = {nom: p * cible / somme for nom, p in brutes.items()}

        return replace(self, selections=tuple(
            s.with_odds(cotes.get(s.selection),
                        no_vig=sans_marge.get(s.selection), overround=overround)
            for s in self.selections))

    @property
    def masse_totale(self) -> float:
        """Somme des probabilités des issues. Doit valoir 1 sur un marché complet
        et mutuellement exclusif — la vérification est faite par les tests de
        cohérence, pas ici : ce module rapporte, il ne juge pas."""
        return sum(s.fair_probability for s in self.selections)


def abstention(
    *, event_id: str, sport: str, family: MarketFamily, status: PricingStatus,
    reason: str, parameters: Mapping | None = None, context: Mapping | None = None,
) -> MarketPricing:
    """Une abstention MOTIVÉE — la seule réponse admise quand on ne sait pas."""
    return MarketPricing(
        event_id=event_id, sport=sport, family=family,
        parameters=dict(parameters or {}), context=dict(context or {}),
        status=status, abstention_reasons=(reason,))


class MarketPricer:
    """Ce qu'un pricer doit savoir faire. Volontairement minimal : `supports`
    répond sur (famille, paramètres), `price` produit ou s'abstient."""

    sport: str
    families: frozenset

    def supports(self, family: MarketFamily, parameters: Mapping) -> bool:  # pragma: no cover
        raise NotImplementedError

    def price(self, *, event, family: MarketFamily, parameters: Mapping,
              context: Mapping) -> MarketPricing:                            # pragma: no cover
        raise NotImplementedError


def avec_fraicheur(prix: "MarketPricing", observed_at, decision_at) -> "MarketPricing":
    """Attache la fraîcheur MESURÉE à un prix. Jamais auto-déclarée.

    L'instant d'observation vient du marché observé, pas du pricer : c'est la
    donnée qui date la donnée. Un pricer qui la fabriquerait s'auto-délivrerait
    le critère.
    """
    from .freshness import evaluer

    mesure = evaluer(observed_at, decision_at)
    return replace(prix, freshness=mesure.score, freshness_detail=mesure)


def price_market(
    *, event, sport: str, family: MarketFamily, parameters: Mapping | None = None,
    context: Mapping | None = None, pricers: Sequence[MarketPricer] = (),
) -> MarketPricing:
    """`(événement, famille, paramètres, contexte)` -> prix, ou abstention motivée.

    Aucune recherche par nom de sport dans une cascade de `if` : un pricer déclare
    ce qu'il couvre, et en ajouter un ne demande pas de toucher cette fonction.
    """
    parametres = dict(parameters or {})
    contexte = dict(context or {})
    event_id = str(getattr(event, "event_id", "") or getattr(event, "id", ""))

    if family is MarketFamily.UNMAPPED:
        return abstention(
            event_id=event_id, sport=sport, family=family,
            status=PricingStatus.UNSUPPORTED, parameters=parametres, context=contexte,
            reason="famille non canonicalisée — il n'y a rien à pricer")

    candidats = [p for p in pricers if p.sport == sport and p.supports(family, parametres)]
    if not candidats:
        return abstention(
            event_id=event_id, sport=sport, family=family,
            status=PricingStatus.MODEL_NOT_AVAILABLE, parameters=parametres, context=contexte,
            reason=f"aucun pricer ne couvre ({sport}, {family.value}, {sorted(parametres)})")

    return candidats[0].price(event=event, family=family,
                              parameters=parametres, context=contexte)
