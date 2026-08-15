"""Ce que le bookmaker expose, tel qu'il l'expose — avant toute interprétation.

Première étape de l'ordre imposé : **observer**. Rien n'est jeté, rien n'est
renommé, rien n'est déduit. Un marché que nous ne savons pas lire doit rester
lisible par quelqu'un d'autre, plus tard, avec ses identifiants d'origine.

LE PARAMÈTRE EST DANS LE PAYLOAD, PAS DANS LE NOM. Mesuré sur une capture réelle
(29 sports, 98 événements, 5 964 marchés) : 1 392 `betTypeName` distincts pour
373 `betType`. L'écart n'est pas de la richesse sémantique, c'est le PARAMÈTRE
recopié dans le libellé — « Nombre de points du joueur - A'ja Wilson »,
« Duo Buteurs - A. Palavecino + R. Lewandowski ». Prendre le libellé pour un type
créerait mille types là où il y en a quelques dizaines, chacun avec ses lignes.

La grammaire de `specialBetValue` est stable et vérifiée sur ces 5 964 marchés :
des couples `clé=valeur` joints par `|`. Aucune valeur sans `=`, aucun `;`.
Quinze clés observées, dont `total`, `hcp`, `player`, `setnr`, `quarternr`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

#: Séparateur de couples dans `specialBetValue` — MESURÉ : 2 798 valeurs composées
#: en portent, aucune n'utilise `;`.
SEPARATEUR = "|"

#: Clés de paramètre observées au moins une fois dans une capture réelle. Cette
#: liste ne FILTRE rien : elle documente ce qui a été vu. Une clé inconnue est
#: conservée telle quelle — c'est précisément le cas qu'il faut pouvoir lire.
CLES_OBSERVEES = frozenset({
    "total", "hcp", "variant", "goals", "type", "periodnr", "goalnr", "player",
    "players", "setnr", "gamenr", "quarternr", "inningnr", "pointnr",
    "competitor", "competitor1", "competitor2", "player1", "player2",
    "from", "to", "framenr",
})

#: Clés qui désignent une PORTION de la rencontre. Un « nombre de points » du
#: 1er quart-temps et celui du match entier sont le même marché à des portées
#: différentes — pas deux marchés (§6).
CLES_DE_PORTEE = ("periodnr", "setnr", "gamenr", "quarternr", "inningnr", "framenr")

#: Clés qui désignent le SUJET du marché : un joueur, une équipe. Même logique —
#: « nombre de points de X » est le marché « nombre de points » appliqué à X.
CLES_DE_SUJET = ("player", "players", "competitor", "competitor1", "competitor2",
                 "player1", "player2")


def parser_parametres(brut: str | None) -> dict[str, str]:
    """`specialBetValue` -> couples. Tolérant, jamais inventif.

    Un fragment sans `=` n'est pas rejeté en silence : il est rangé sous la clé
    vide, ce qui le rend visible à l'inventaire. Sur la capture réelle il n'y en
    a aucun — mais un format qui change sans prévenir doit se voir, pas
    disparaître.
    """
    if not brut:
        return {}
    parametres: dict[str, str] = {}
    for fragment in str(brut).split(SEPARATEUR):
        if not fragment:
            continue
        cle, sep, valeur = fragment.partition("=")
        if sep:
            parametres[cle] = valeur
        else:
            parametres.setdefault("", "")
            parametres[""] = (parametres[""] + " " + fragment).strip()
    return parametres


def _nombre(valeur: str | None) -> float | None:
    """Une ligne numérique, ou rien. `None` veut dire « pas un nombre », jamais 0."""
    if valeur is None:
        return None
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RawSelectionObservation:
    """Une sélection telle que reçue. `odds` peut manquer — l'absence de cote est
    une information (marché suspendu), pas un zéro."""

    source_selection_id: str | None
    code: str | None
    label: str | None
    decimal_odds: float | None
    competitor_id: str | None = None
    available: bool | None = None


@dataclass(frozen=True)
class RawMarketObservation:
    """Un marché observé chez un bookmaker, intégralement conservé.

    `extras` recueille tout champ que ce modèle ne nomme pas : le jour où le
    bookmaker en ajoute un, il arrive dans l'inventaire au lieu d'être perdu
    entre le parsing et la relecture.
    """

    bookmaker: str
    sport: str
    sport_id: int | None
    competition: str | None
    competition_source_id: str | None
    source_event_id: str
    event_label: str | None
    start_time: datetime | None
    is_outright: bool
    market_source_id: str | None
    bet_type: int | None                       # identifiant de FAMILLE côté source
    bet_type_name: str | None                  # libellé, paramètre compris
    bet_title: str | None
    template: str | None                       # forme déclarée par la source
    special_bet_value: str | None              # paramètres, verbatim
    category_id: int | None = None
    category: str | None = None
    is_live: bool | None = None
    selections: tuple[RawSelectionObservation, ...] = ()
    observed_at: datetime | None = None
    extras: dict = field(default_factory=dict)

    @property
    def parametres(self) -> dict[str, str]:
        return parser_parametres(self.special_bet_value)

    @property
    def ligne(self) -> float | None:
        """Le seuil d'un marché de total (`total=2.5`), s'il y en a un."""
        return _nombre(self.parametres.get("total"))

    @property
    def handicap(self) -> float | None:
        return _nombre(self.parametres.get("hcp"))

    @property
    def portee(self) -> dict[str, str]:
        """Les clés qui restreignent le marché à une portion de la rencontre."""
        p = self.parametres
        return {c: p[c] for c in CLES_DE_PORTEE if c in p}

    @property
    def sujet(self) -> dict[str, str]:
        """Les clés qui désignent un joueur ou une équipe."""
        p = self.parametres
        return {c: p[c] for c in CLES_DE_SUJET if c in p}

    @property
    def cles_inconnues(self) -> tuple[str, ...]:
        """Paramètres jamais rencontrés lors de la cartographie. À surveiller :
        c'est par là qu'un marché change de sens sans prévenir."""
        return tuple(sorted(c for c in self.parametres if c and c not in CLES_OBSERVEES))

    @property
    def nb_selections(self) -> int:
        return len(self.selections)


def sport_id_de(nom: str | None) -> int | None:
    """Nom de sport -> `sportId` bookmaker. La table du connecteur est l'autorité :
    le registre de capacité est indexé dessus, et une valeur absente ferait
    silencieusement échouer toutes les résolutions."""
    from ..bookmakers.winamax.connector import SPORT_IDS
    return SPORT_IDS.get((nom or "").lower())


def observation_de_marche(raw_event, raw_market, *, competition=None) -> RawMarketObservation:
    """`RawMarket` du connecteur -> observation d'inventaire.

    Conversion de FORME uniquement : aucun champ n'est inventé, et les codes bruts
    sont conservés tels quels pour la liaison des sélections.

    Cette fonction est PARTAGÉE par la collecte CLV et par le chemin produit. Deux
    conversions séparées finiraient par lire le même marché différemment — l'une
    attacherait le `betType`, l'autre non — et la CLV mesurerait alors un contrat
    que le produit n'a jamais évalué.
    """
    return RawMarketObservation(
        bookmaker=raw_event.bookmaker,
        sport=raw_event.sport,
        sport_id=sport_id_de(raw_event.sport),
        competition=competition or getattr(raw_event, "competition", None),
        competition_source_id=getattr(raw_event, "raw_tournament_id", None),
        source_event_id=raw_event.bookmaker_event_id,
        event_label=f"{raw_event.slot_1_name} - {raw_event.slot_2_name}",
        start_time=raw_event.start_time,
        is_outright=bool(getattr(raw_event, "is_outright", False)),
        market_source_id=getattr(raw_market, "market_source_id", None),
        bet_type=getattr(raw_market, "raw_bet_type", None),
        bet_type_name=getattr(raw_market, "raw_label", None),
        bet_title=None,
        template=getattr(raw_market, "template", None),
        special_bet_value=getattr(raw_market, "special_bet_value", None),
        is_live=getattr(raw_market, "is_live", None),
        selections=tuple(
            RawSelectionObservation(
                source_selection_id=None, code=s.code, label=s.label,
                decimal_odds=s.decimal_odds)
            for s in raw_market.selections),
        observed_at=raw_event.fetched_at,
    )
