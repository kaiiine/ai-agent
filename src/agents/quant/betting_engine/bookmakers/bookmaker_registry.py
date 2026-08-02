"""Rattachement d'un événement Winamax scanné à l'identité canonique (§5.1).

Répond à : « cet événement bookmaker correspond à quel événement canonique,
avec quels participants, dans quelle compétition ? » — distinct du Competition
Registry (couverture stats) et du Canonical Event Registry (§5.2).

DISTINGUO IMPORTANT (ADR-015). La résolution d'identité par **nom/alias** posée
ici est un mécanisme de BOOTSTRAP, PAS sanctionné par l'ADR-015. L'ADR-015
valide uniquement la traduction du **rôle** — un participant *déjà résolu* ->
`home`/`away` — pas la fiabilité de la résolution d'identité par nom. Ce sont
deux étapes distinctes et successives :
  1. identité  : qui est ce participant -> `canonical_id`  (ce module)
  2. rôle      : quel rôle sportif       -> `ParticipantRoleResolver` (ADR-015)

La résolution par nom respecte la mise en garde de la gateway (« nom = fragile,
alimenté à la main ») via des garde-fous stricts : correspondance nom/alias
EXACTE (jamais approximative), statut explicite pour chaque cas, et un seam vers
la résolution autoritaire par ID provider (`canonicalize`) qui prime dès que des
IDs Winamax seront peuplés — un désaccord ID/nom devenant alors un `CONFLICT`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver, IdentityStatus

from .canonical_event import build_canonical_event_key
from .participant_role_resolver import ParticipantRoleResolver
from .protocol import RawBookmakerEvent
from .winamax.competition_mapping import resolve_competition as _default_resolve_competition

# --- Point 5 : éligibilité SÉPARÉE de l'identité -------------------------------
# L'identité dit « a-t-on pu résoudre qui/où » ; l'éligibilité dit « cet
# événement est-il dans le périmètre du pipeline ». Ne JAMAIS mélanger les deux.
# Le principe généralise (marché exotique non supporté, etc.).
EligibilityStatus = Literal["ELIGIBLE", "UNSUPPORTED_EVENT_TYPE"]

# --- Point 6 : ordre de sévérité EXPLICITE ------------------------------------
# CONFLICT > AMBIGUOUS > UNRESOLVED > RESOLVED.
SEVERITY_ORDER: tuple[IdentityStatus, ...] = ("RESOLVED", "UNRESOLVED", "AMBIGUOUS", "CONFLICT")
_RANK: dict[str, int] = {status: i for i, status in enumerate(SEVERITY_ORDER)}


def most_severe(statuses: list[IdentityStatus]) -> IdentityStatus:
    """Statut le plus sévère selon `SEVERITY_ORDER` (le pire l'emporte)."""
    return max(statuses, key=lambda s: _RANK[s])


# --- Point 3 : traçabilité structurée, une preuve par sous-résolution ---------
@dataclass(frozen=True)
class ResolutionEvidence:
    """Trace auditable d'UNE sous-résolution (un participant, ou la compétition).

    Structure complète dès maintenant (comme `CanonicalEnvelope` en Vague 0) :
    `BookmakerEventMapping` sert de référence d'audit durable, on ne veut pas
    migrer un format minimal plus tard.
    """

    subject: str                           # "slot_1" | "slot_2" | "competition"
    raw_input: str                         # nom brut Winamax, ou tournamentId brut
    method: str                            # provider_id | name_exact | name_alias | name_multi | competition_table | unverified | none
    status: IdentityStatus
    canonical_id: str | None
    candidates: tuple[str, ...] = ()        # canonical_ids en compétition si AMBIGUOUS/CONFLICT


@dataclass(frozen=True)
class BookmakerEventMapping:
    """Rattachement d'un événement bookmaker à l'identité canonique (§5.1)."""

    bookmaker: str
    bookmaker_event_id: str
    sport: str
    canonical_event_id: str | None          # non nul seulement si identity_status == RESOLVED
    competition_id: str | None
    identity_status: IdentityStatus
    eligibility_status: EligibilityStatus
    evidence: tuple[ResolutionEvidence, ...]
    confirmed_at: datetime

    @property
    def is_usable(self) -> bool:
        """Consommable en aval : identité résolue ET événement éligible."""
        return self.identity_status == "RESOLVED" and self.eligibility_status == "ELIGIBLE"


CompetitionResolver = Callable[[str | None], "tuple[str | None, str, str]"]


# Types d'entités pouvant être PARTICIPANT d'un événement. Générique : un sport
# d'équipes peuple `team:{sport}:…`, un sport individuel (tennis, MMA) `player:{sport}:…`.
# Aucun `if sport == …` : la résolution cherche dans les deux espaces, qui ne se croisent
# jamais (le préfixe entity_type est structurellement obligatoire, GW-FR-008).
PARTICIPANT_ENTITY_TYPES = ("team", "player")


class BookmakerEventResolver:
    """Résout un `RawBookmakerEvent` en `BookmakerEventMapping`.

    Consomme la gateway UNIQUEMENT en lecture (IdentityResolver, table de
    compétition) — aucune modification de code gateway.
    """

    def __init__(
        self,
        identity_resolver: IdentityResolver,
        *,
        role_resolver: ParticipantRoleResolver | None = None,
        competition_resolver: CompetitionResolver | None = None,
    ):
        self._identity = identity_resolver
        self._roles = role_resolver or ParticipantRoleResolver()
        self._resolve_competition = competition_resolver or _default_resolve_competition

    def resolve_event(self, event: RawBookmakerEvent) -> BookmakerEventMapping:
        confirmed_at = datetime.now(timezone.utc)

        # Point 5 : un outright est résoluble ou non, mais reste hors périmètre
        # par TYPE — éligibilité distincte, jamais fondue dans l'identité.
        if event.is_outright:
            return BookmakerEventMapping(
                bookmaker=event.bookmaker, bookmaker_event_id=event.bookmaker_event_id,
                sport=event.sport, canonical_event_id=None, competition_id=None,
                identity_status="UNRESOLVED", eligibility_status="UNSUPPORTED_EVENT_TYPE",
                evidence=(), confirmed_at=confirmed_at,
            )

        ev_1 = self._resolve_participant(event.sport, "slot_1", event.slot_1_name, event.slot_1_id)
        ev_2 = self._resolve_participant(event.sport, "slot_2", event.slot_2_name, event.slot_2_id)

        comp_id, comp_status, comp_method = self._resolve_competition(event.raw_tournament_id)
        ev_comp = ResolutionEvidence(
            "competition", event.raw_tournament_id or "", comp_method,
            comp_status, comp_id,
        )

        evidence = (ev_1, ev_2, ev_comp)
        identity_status = most_severe([ev_1.status, ev_2.status, ev_comp.status])

        canonical_event_id = None
        if identity_status == "RESOLVED" and event.start_time is not None:
            role_by_slot = {p.bookmaker_slot: p.role for p in self._roles.resolve(event)}
            canonical_event_id = build_canonical_event_key(
                sport=event.sport,
                competition_id=comp_id,
                scheduled_at=event.start_time,
                participants_with_roles=[
                    (role_by_slot["slot_1"], ev_1.canonical_id),
                    (role_by_slot["slot_2"], ev_2.canonical_id),
                ],
            )

        return BookmakerEventMapping(
            bookmaker=event.bookmaker, bookmaker_event_id=event.bookmaker_event_id,
            sport=event.sport, canonical_event_id=canonical_event_id,
            competition_id=comp_id, identity_status=identity_status,
            eligibility_status="ELIGIBLE", evidence=evidence, confirmed_at=confirmed_at,
        )

    # -- sous-résolution d'un participant ------------------------------------
    def _resolve_participant(
        self, sport: str, subject: str, raw_name: str, raw_id: str | None
    ) -> ResolutionEvidence:
        # 1. Voie autoritaire : ID provider Winamax (seam, prime quand peuplé).
        id_cid: str | None = None
        id_status: IdentityStatus = "UNRESOLVED"
        if raw_id is not None:
            for entity_type in PARTICIPANT_ENTITY_TYPES:
                id_cid, id_status = self._identity.canonicalize("winamax", str(raw_id), entity_type)
                if id_status == "RESOLVED":
                    break

        # 2. Correspondance nom/alias EXACTE (bootstrap), côté betting_engine.
        matches, alias_hit = self._name_matches(sport, raw_name)

        if id_status == "RESOLVED":
            # Contre-vérification : un nom qui pointe ailleurs = CONFLICT, jamais
            # un choix silencieux entre deux identités contradictoires.
            if len(matches) == 1 and matches[0].canonical_id != id_cid:
                return ResolutionEvidence(
                    subject, raw_name, "provider_id", "CONFLICT", id_cid,
                    candidates=tuple(sorted({id_cid, matches[0].canonical_id})),
                )
            return ResolutionEvidence(subject, raw_name, "provider_id", "RESOLVED", id_cid)

        if len(matches) == 1:
            entity = matches[0]
            method = "name_alias" if alias_hit[entity.canonical_id] else "name_exact"
            return ResolutionEvidence(subject, raw_name, method, "RESOLVED", entity.canonical_id)

        if len(matches) >= 2:
            return ResolutionEvidence(
                subject, raw_name, "name_multi", "AMBIGUOUS", None,
                candidates=tuple(sorted(e.canonical_id for e in matches)),
            )

        return ResolutionEvidence(subject, raw_name, "none", "UNRESOLVED", None)

    def _name_matches(self, sport: str, raw_name: str):
        """Correspondance EXACTE (strip + casefold) sur canonical_name ou alias.

        Aucune approximation : un alias non enregistré ne matche jamais, même
        visuellement proche du nom canonique (« Paris S-G » ne matche pas PSG).
        On parcourt toutes les entités du sport pour pouvoir COMPTER les
        correspondances et détecter une vraie ambiguïté (ce que `find_by_name`,
        qui s'arrête au premier match, masquerait).
        """
        needle = (raw_name or "").strip().casefold()
        matches = []
        alias_hit: dict[str, bool] = {}
        if not needle:
            return matches, alias_hit
        entities = [e for t in PARTICIPANT_ENTITY_TYPES
                    for e in self._identity.all_entities(f"{t}:{sport}:")]
        for entity in entities:
            if entity.canonical_name.strip().casefold() == needle:
                matches.append(entity)
                alias_hit[entity.canonical_id] = False
            elif any(a.strip().casefold() == needle for a in entity.aliases):
                matches.append(entity)
                alias_hit[entity.canonical_id] = True
        return matches, alias_hit
