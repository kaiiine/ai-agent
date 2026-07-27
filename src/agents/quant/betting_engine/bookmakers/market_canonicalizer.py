"""Canonicalisation ATOMIQUE d'un marché bookmaker -> OddsSnapshot (§4.2).

Le dernier maillon côté COTES : slots bruts (`slot_1`/`slot_2`/`draw`) ->
sélections canoniques (`home`/`away`/`draw`), en appliquant la résolution des
rôles fournie par le `ParticipantRoleResolver` — **jamais** de convention
`slot_1 == home` ici. La cote suit toujours le rôle résolu.

Atomique : pour un 1X2, soit les TROIS `OddsSnapshot` sont produits, soit aucun
(jamais un marché partiel transmis au value_engine). Tout échec est un RÉSULTAT
typé auditable (statut + raison + contexte structuré), jamais un skip silencieux,
jamais une exception (appelé par-marché sur un scan en masse). `MarketCoherenceError`
reste la défense en profondeur du value_engine pour ce qui contournerait la glue.

Ce module ne ferme QUE la branche cotes :
    scan Winamax -> événement résolu -> marché canonicalisé -> OddsSnapshot -> value_engine.
Il ne produit PAS de MarketPrediction (branche sport, orchestrateur live à venir).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from src.agents.quant.betting_engine.core.odds import OddsSnapshot

from .bookmaker_registry import BookmakerEventMapping
from .participant_role_resolver import ParticipantRoleResolver
from .protocol import MarketType, RawBookmakerEvent, RawMarket

_CANONICAL_MARKET_TYPE = "MATCH_WINNER"
_EXPECTED_1X2_SLOTS = ("draw", "slot_1", "slot_2")   # trié


class MarketCanonicalizationStatus(str, Enum):
    OK = "OK"
    EVENT_NOT_RESOLVED = "EVENT_NOT_RESOLVED"     # identité non RESOLVED (UNRESOLVED/AMBIGUOUS/CONFLICT)
    EVENT_NOT_ELIGIBLE = "EVENT_NOT_ELIGIBLE"     # RESOLVED mais eligibility != ELIGIBLE (distinct !)
    UNSUPPORTED_MARKET = "UNSUPPORTED_MARKET"     # marché connu hors scope (outright, 2way, non-1X2)
    INVALID_MARKET_DATA = "INVALID_MARKET_DATA"   # 1X2 prétendu mais malformé / assemblage incohérent


@dataclass(frozen=True)
class ParticipantRoleResolution:
    """Sortie du `ParticipantRoleResolver`, ancrée à l'événement bookmaker.

    Construite via `resolve_participant_roles` — la glue la CONSOMME, elle ne
    ré-infère jamais un rôle."""

    bookmaker_event_id: str
    roles: dict[str, str]                          # {"slot_1": "home"/"away", "slot_2": ...}


@dataclass(frozen=True)
class MarketCanonicalizationResult:
    status: MarketCanonicalizationStatus
    reason: str
    bookmaker_event_id: str
    canonical_event_id: str | None
    market_id: str | None
    snapshots: tuple[OddsSnapshot, ...] = ()       # vide sauf si OK
    details: dict = field(default_factory=dict)

    @property
    def is_ok(self) -> bool:
        return self.status is MarketCanonicalizationStatus.OK


def build_market_id(bookmaker: str, canonical_event_id: str, market_type: str) -> str:
    """Construction DÉTERMINISTE et UNIQUE du market_id (identité logique du
    marché) : stable pour un marché observé, indépendante de la sélection et du
    timestamp. Deux observations du même marché partagent ce market_id et se
    distinguent par `observed_at`."""
    return f"{bookmaker}:{canonical_event_id}:{market_type}"


def resolve_participant_roles(
    raw_event: RawBookmakerEvent, role_resolver: ParticipantRoleResolver | None = None
) -> ParticipantRoleResolution:
    """Enveloppe la SEULE autorité des rôles (`ParticipantRoleResolver`) et
    l'ancre à l'événement bookmaker."""
    resolver = role_resolver or ParticipantRoleResolver()
    roles = {p.bookmaker_slot: p.role for p in resolver.resolve(raw_event)}
    return ParticipantRoleResolution(raw_event.bookmaker_event_id, roles)


def _fail(status, reason, mapping, *, details=None) -> MarketCanonicalizationResult:
    return MarketCanonicalizationResult(
        status=status, reason=reason,
        bookmaker_event_id=mapping.bookmaker_event_id,
        canonical_event_id=mapping.canonical_event_id,
        market_id=None, snapshots=(), details=details or {},
    )


def canonicalize_market(
    raw_event: RawBookmakerEvent,
    raw_market: RawMarket,
    event_mapping: BookmakerEventMapping,
    role_resolution: ParticipantRoleResolution,
    *,
    observed_at: datetime | None = None,
) -> MarketCanonicalizationResult:
    bem_id = event_mapping.bookmaker_event_id

    # 1) Cohérence d'assemblage : les 3 objets concernent le MÊME événement bookmaker.
    if raw_event.bookmaker_event_id != bem_id or role_resolution.bookmaker_event_id != bem_id:
        return _fail(
            MarketCanonicalizationStatus.INVALID_MARKET_DATA,
            "objets d'événements différents assemblés",
            event_mapping,
            details={"raw_event": raw_event.bookmaker_event_id,
                     "mapping": bem_id,
                     "role_resolution": role_resolution.bookmaker_event_id},
        )
    if not any(raw_market is m for m in raw_event.markets):
        return _fail(
            MarketCanonicalizationStatus.INVALID_MARKET_DATA,
            "le marché n'appartient pas à l'événement fourni", event_mapping,
        )

    # 2) Identité PUIS éligibilité — deux échecs DISTINCTS.
    if event_mapping.identity_status != "RESOLVED":
        return _fail(MarketCanonicalizationStatus.EVENT_NOT_RESOLVED,
                     f"identity_status={event_mapping.identity_status}", event_mapping,
                     details={"identity_status": event_mapping.identity_status})
    if event_mapping.eligibility_status != "ELIGIBLE":
        return _fail(MarketCanonicalizationStatus.EVENT_NOT_ELIGIBLE,
                     f"eligibility_status={event_mapping.eligibility_status}", event_mapping,
                     details={"eligibility_status": event_mapping.eligibility_status})

    # 3) Marché supporté : 1X2 = MATCH_WINNER + template 3way (avec nul).
    if raw_market.market_type is not MarketType.MATCH_WINNER or raw_market.template != "3way":
        return _fail(MarketCanonicalizationStatus.UNSUPPORTED_MARKET,
                     f"marché hors scope ({raw_market.market_type.value}/{raw_market.template})",
                     event_mapping,
                     details={"market_type": raw_market.market_type.value, "template": raw_market.template})

    # 4) Issues : exactement {slot_1, draw, slot_2}, aucune dupliquée/inconnue, cotes>1.
    selections = list(raw_market.selections)
    canon = [s.canonical_selection for s in selections]
    if len(canon) != 3:
        return _fail(MarketCanonicalizationStatus.INVALID_MARKET_DATA,
                     f"nombre d'issues 1X2 != 3 (reçu {len(canon)})", event_mapping,
                     details={"selections": canon})
    if sorted(canon) != list(_EXPECTED_1X2_SLOTS):
        return _fail(MarketCanonicalizationStatus.INVALID_MARKET_DATA,
                     "issues 1X2 invalides (dupliquée / inconnue / nul manquant)", event_mapping,
                     details={"selections": canon, "attendu": list(_EXPECTED_1X2_SLOTS)})
    invalid_odds = [s.canonical_selection for s in selections if s.decimal_odds <= 1.0]
    if invalid_odds:
        return _fail(MarketCanonicalizationStatus.INVALID_MARKET_DATA,
                     "cote invalide (<= 1)", event_mapping, details={"selections": invalid_odds})

    # 5) La résolution couvre bien les deux slots.
    missing = [slot for slot in ("slot_1", "slot_2") if slot not in role_resolution.roles]
    if missing:
        return _fail(MarketCanonicalizationStatus.INVALID_MARKET_DATA,
                     "slot absent de la résolution des rôles", event_mapping,
                     details={"slots_manquants": missing, "roles": role_resolution.roles})

    # 6) Traduction ATOMIQUE : la cote suit le rôle résolu (jamais slot_1==home).
    canonical_event_id = event_mapping.canonical_event_id
    market_id = build_market_id(event_mapping.bookmaker, canonical_event_id, _CANONICAL_MARKET_TYPE)
    when = observed_at or raw_event.fetched_at
    snapshots = tuple(
        OddsSnapshot(
            event_id=canonical_event_id,
            market_type=_CANONICAL_MARKET_TYPE,
            selection=("draw" if s.canonical_selection == "draw"
                       else role_resolution.roles[s.canonical_selection]),
            decimal_odds=s.decimal_odds,
            observed_at=when,
            bookmaker=event_mapping.bookmaker,
            is_boosted=s.is_boosted,
            boost_reference_odds=s.boost_reference_odds,
            max_stake=s.max_stake,
            max_payout=s.max_payout,
        )
        for s in selections
    )
    return MarketCanonicalizationResult(
        status=MarketCanonicalizationStatus.OK, reason="ok",
        bookmaker_event_id=bem_id, canonical_event_id=canonical_event_id,
        market_id=market_id, snapshots=snapshots,
        details={"roles": role_resolution.roles, "market_id": market_id},
    )
