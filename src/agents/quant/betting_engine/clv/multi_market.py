"""Collecte CLV sur TOUS les marchés d'un événement, en un seul passage réseau.

`record_odds` ne voit que le marché « qui gagne » : il cherche LE marché du
schéma du sport et ignore les 250 autres que la page expose. Tant qu'une seule
famille était modélisée, c'était exact. Depuis que le Plus/Moins, la double
chance, le remboursé-si-nul et le score exact sont priceables, leur CLV ne se
collectera jamais toute seule — et sans CLV, aucune de ces capacités ne sortira
jamais d'EXPERIMENTAL.

CE MODULE N'EST PAS UN SECOND CHEMIN. Il réutilise, dans l'ordre, exactement les
composants déjà éprouvés :

    build_row                  famille canonique + paramètres    (markets/inventory)
    resolve_model              la capacité existe-t-elle ?       (markets/capability)
    canonicaliser_selections   codes -> sélections, par les codes (markets/selection_binding)
    identite_contrat           l'identité économique complète     (clv/contract)

`record_odds` reste intact et continue de servir le chemin historique.

RIEN N'EST JETÉ EN SILENCE. Chaque marché non collecté est compté sous son motif :
famille non démontrée, portée incompatible, capacité absente, sélection non
canonicalisable, cote manquante. Un compteur qui ne bouge pas est une information ;
un marché disparu sans trace n'en est pas une.

UN SEUL PASSAGE RÉSEAU. Ce module ne fetch rien : il consomme les événements déjà
scannés, avec leurs marchés. Le coût croît avec le nombre de marchés lus, jamais
avec le nombre d'appels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..bookmakers.canonical_binding import build_canonical_event
from ..bookmakers.market_canonicalizer import resolve_participant_roles
from ..markets.capability import CapabilityStatus, resolve_model
from ..markets.families import MarketFamily
from ..markets.inventory import build_row
from ..markets.observation import RawMarketObservation, RawSelectionObservation
from ..markets.selection_binding import canonicaliser_selections
from .contract import identite_contrat
from .observation import ObservationPhase, OddsObservation
from .recorder import closing_is_valid


@dataclass
class MultiMarketSummary:
    """Ce que la passe a vu, et ce qu'elle n'a pas retenu — avec le motif."""

    events_seen: int = 0
    events_recorded: int = 0
    events_unusable: int = 0
    events_started: int = 0
    markets_seen: int = 0
    markets_canonicalized: int = 0
    markets_capability_available: int = 0
    markets_recorded: int = 0
    markets_skipped_context: int = 0
    markets_skipped_model: int = 0
    markets_selection_failed: int = 0
    markets_rule_unknown: int = 0
    markets_no_odds: int = 0
    selections_written: int = 0
    contracts: dict = field(default_factory=dict)      # identité -> nb de sélections

    def describe(self) -> str:
        return (f"{self.events_recorded}/{self.events_seen} événement(s), "
                f"{self.markets_recorded}/{self.markets_seen} marché(s) retenu(s), "
                f"{self.selections_written} sélection(s) écrite(s)")


def _sport_id(nom: str) -> int | None:
    """Nom de sport -> `sportId` bookmaker. La table du connecteur est l'autorité :
    le registre de capacité est indexé dessus, et une valeur absente ferait
    silencieusement échouer toutes les résolutions."""
    from ..bookmakers.winamax.connector import SPORT_IDS
    return SPORT_IDS.get((nom or "").lower())


def _observation_de_marche(raw_event, raw_market, *, competition=None) -> RawMarketObservation:
    """`RawMarket` du connecteur -> observation d'inventaire.

    Conversion de forme uniquement : aucun champ n'est inventé, et les codes
    bruts sont conservés tels quels pour la liaison des sélections.
    """
    return RawMarketObservation(
        bookmaker=raw_event.bookmaker,
        sport=raw_event.sport,
        sport_id=_sport_id(raw_event.sport),
        competition=competition or getattr(raw_event, "competition", None),
        competition_source_id=getattr(raw_event, "raw_tournament_id", None),
        source_event_id=raw_event.bookmaker_event_id,
        event_label=f"{raw_event.slot_1_name} - {raw_event.slot_2_name}",
        start_time=raw_event.start_time,
        is_outright=bool(getattr(raw_event, "is_outright", False)),
        market_source_id=None,
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


def record_all_markets(
    events, *, event_resolver, store, phase: ObservationPhase, source: str,
    run_id: str | None = None, role_resolver=None,
    winamax_sport_id: int | None = 1,
) -> MultiMarketSummary:
    """Écrit une observation par sélection collectable, pour TOUS les marchés.

    L'ordre des contrôles n'est pas arbitraire : on ne demande jamais au registre
    de capacité ce qu'il pense d'un marché dont la famille n'est pas établie, et
    on ne lie jamais des sélections d'un marché qu'aucun modèle ne couvre. Chaque
    étape a son compteur, et les compteurs se somment.
    """
    resume = MultiMarketSummary()

    for raw_event in events:
        resume.events_seen += 1
        mapping = event_resolver.resolve_event(raw_event)
        if not mapping.is_usable:
            resume.events_unusable += 1
            continue
        evenement = build_canonical_event(raw_event, mapping, role_resolver)
        if evenement is None:
            resume.events_unusable += 1
            continue

        # Le garde de clôture porte sur l'ÉVÉNEMENT : une cote de direct n'est
        # une ligne de clôture pour aucun de ses marchés.
        if phase is ObservationPhase.CLOSING and not closing_is_valid(
                raw_event, raw_event.fetched_at):
            resume.events_started += 1
            continue

        roles = dict(resolve_participant_roles(raw_event, role_resolver).roles)

        ecrites_pour_evenement = 0
        for raw_market in raw_event.markets:
            resume.markets_seen += 1
            obs = _observation_de_marche(raw_event, raw_market,
                                         competition=mapping.competition_id)
            ligne = build_row(obs)

            if not ligne.classification.canonical:
                resume.markets_rule_unknown += 1
                continue
            resume.markets_canonicalized += 1

            statut = ligne.capability.status
            if statut is CapabilityStatus.MODEL_CONTEXT_MISMATCH:
                resume.markets_skipped_context += 1
                continue
            if statut is not CapabilityStatus.MODEL_AVAILABLE:
                resume.markets_skipped_model += 1
                continue
            resume.markets_capability_available += 1

            binding = canonicaliser_selections(
                family=ligne.family, codes=[s.code for s in obs.selections], roles=roles)
            if not binding.complete:
                resume.markets_selection_failed += 1
                continue

            cotees = [s for s in obs.selections if s.decimal_odds and s.decimal_odds > 1.0]
            if not cotees:
                resume.markets_no_odds += 1
                continue

            contrat = identite_contrat(ligne.family, ligne.classification.parameters)
            for selection in cotees:
                store.append(OddsObservation(
                    event_id=evenement.event_id,
                    market_type=contrat,
                    selection=binding.par_code[selection.code],
                    bookmaker=raw_event.bookmaker,
                    decimal_odds=Decimal(str(selection.decimal_odds)),
                    observed_at=raw_event.fetched_at,
                    phase=phase,
                    source=source,
                    source_event_id=raw_event.bookmaker_event_id,
                    run_id=run_id))
                resume.selections_written += 1
                resume.contracts[contrat] = resume.contracts.get(contrat, 0) + 1
            resume.markets_recorded += 1
            ecrites_pour_evenement += 1

        if ecrites_pour_evenement:
            resume.events_recorded += 1

    return resume
