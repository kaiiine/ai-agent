"""Contrat commun d'acquisition bookmaker + vocabulaire canonique partagé.

Objets d'ACQUISITION uniquement : on conserve l'ordre brut du bookmaker en
**slots** (`slot_1`/`slot_2`), jamais de sémantique `home`/`away` à ce niveau
(cf. §5.2bis du PRD + ADR-015). La traduction slot -> rôle sportif canonique est
la responsabilité du `ParticipantRoleResolver`, pas du connecteur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable


class MarketType(str, Enum):
    """Vocabulaire canonique de marchés, partagé par tous les bookmakers.

    Volontairement minimal : on ne canonise que ce qui est explicitement observé
    dans le snapshot réel (règle sûre carto #3). Tout marché non reconnu est
    `UNMAPPED` — jamais deviné (règle sûre #5).
    """

    MATCH_WINNER = "MATCH_WINNER"        # « qui gagne » : 1X2 (foot) ou 2-way (tennis, baseball)
    OUTRIGHT_WINNER = "OUTRIGHT_WINNER"  # vainqueur d'une épreuve/compétition (F1, cyclisme...)
    UNMAPPED = "UNMAPPED"                # aucun mapping direct — signalé, jamais inféré


@dataclass(frozen=True)
class RawSelection:
    """Une sélection telle qu'acquise chez le bookmaker, avec sa cote.

    `canonical_selection` référence un **slot** (`slot_1`/`slot_2`/`draw`), pas un
    rôle : la résolution en rôle sportif se fait plus loin via le
    `ParticipantRoleResolver`, en combinant le slot et le sport.

    Les champs d'offre (`is_boosted`, `boost_reference_odds`, `max_stake`,
    `max_payout`) correspondent aux propriétés d'`OddsSnapshot` du PRD (§5.3,
    ADR-017 : une cote boostée reste sur le même marché, ce n'est pas un
    `market_type` distinct). En pré-match non boosté — le seul périmètre actif —
    ils restent à leur valeur par défaut ; leur peuplement (cotes boostées) est
    différé en Vague 2 (cf. `winamax/market_mapping.py`).
    """

    code: str                              # code brut Winamax ("1"/"x"/"2"...)
    label: str                             # libellé lisible ("Copenhague", "Match nul"...)
    decimal_odds: float
    canonical_selection: str               # "slot_1" | "slot_2" | "draw" | "UNMAPPED"
    is_boosted: bool = False
    boost_reference_odds: float | None = None
    max_stake: float | None = None
    max_payout: float | None = None


@dataclass(frozen=True)
class RawMarket:
    """Un marché acquis pour un événement : son type canonique + ses sélections."""

    market_type: MarketType
    raw_bet_type: int                      # betType Winamax brut (conservé, namespace fournisseur)
    raw_label: str                         # betTypeName brut ("Résultat", "Vainqueur"...)
    template: str                          # "3way" | "2way" | "ListOdd"
    is_live: bool
    special_bet_value: str | None
    selections: list[RawSelection]
    #: Identifiant du marché CHEZ LE BOOKMAKER (`betId` Winamax). La provenance
    #: d'un chiffre affiché doit remonter jusqu'à la ligne du bookmaker, et
    #: `(événement, betType, specialBetValue)` ne suffit pas : deux marchés
    #: peuvent partager les trois. `None` quand la source n'en expose pas —
    #: jamais un identifiant fabriqué.
    market_source_id: str | None = None


@dataclass(frozen=True)
class RawBookmakerEvent:
    """Un événement pariable tel qu'acquis, en slots — AUCUN home/away ici.

    On conserve tous les IDs bruts dans un namespace fournisseur (règle sûre #1)
    et les indices d'appariement (`sr_tournament_id`) utiles au futur
    `bookmaker_registry` pour rattacher à un `canonical_event_id`.
    """

    bookmaker: str
    bookmaker_event_id: str
    sport: str
    competition: str
    slot_1_name: str
    slot_2_name: str
    slot_1_id: str | None
    slot_2_id: str | None
    start_time: datetime | None
    status: str                            # "PREMATCH" | "LIVE" (brut Winamax)
    is_outright: bool
    markets: list[RawMarket]
    fetched_at: datetime
    sr_tournament_id: str | None = None
    raw_tournament_id: str | None = None
    #: Nombre de marchés que la SOURCE déclare pour cet événement (`moreBets`).
    #: La page catalogue n'en sert qu'un ; ce compte est le seul moyen de dire,
    #: sans les télécharger, combien on n'a PAS regardés. `None` = non déclaré,
    #: jamais confondu avec « aucun autre marché ».
    declared_market_count: int | None = None


@dataclass(frozen=True)
class EventParticipant:
    """Un participant et son **rôle** canonique dans l'événement (§5.2 du PRD).

    `role` est la vérité sportive (`home`/`away`, `player_a`/`player_b`...),
    déclarée par le sport. `bookmaker_slot` conserve le slot d'origine pour
    l'audit — utile pour détecter qu'un bookmaker change sa convention
    d'affichage (§5.2bis) — mais ne doit jamais être confondu avec le rôle.
    """

    role: str
    name: str
    bookmaker_slot: str                    # "slot_1" | "slot_2"


@runtime_checkable
class BookmakerConnector(Protocol):
    """Contrat commun (§4.1 du PRD). Ajouter un bookmaker = l'implémenter."""

    bookmaker: str

    def scan_catalog(self, sport: str) -> list[RawBookmakerEvent]:
        """Scanne le catalogue du bookmaker et renvoie ses événements en slots.

        `sport` est OBLIGATOIRE. Il a longtemps valu « football » par défaut :
        un appelant générique en apparence scannait alors le football sans le
        dire, et le silence ressemblait à un résultat vide. Un défaut ne se
        remarque pas à la lecture — une erreur d'appel, si.
        """
        ...

    def market_mapping(self) -> dict:
        """Table des libellés/types bruts de ce bookmaker -> `MarketType`."""
        ...
