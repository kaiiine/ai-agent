"""Traduction slot bookmaker -> rôle sportif canonique (ADR-015, §5.2bis du PRD).

Composant DISTINCT des normalizers de la gateway : ceux-ci convertissent
provider brut -> faits canoniques (ADR-003) ; ici on traduit une position
d'affichage bookmaker (`slot_1`/`slot_2`) en rôle sportif (`home`/`away`,
`player_a`/`player_b`...). Le nom évite délibérément « Normalizer », réservé à
la gateway.

Point crucial (ADR-015) : pour le football, `slot_1 -> home` repose sur une
vérification EMPIRIQUE (49/49 sur 8 compétitions), pas sur une équivalence
structurelle. Si une re-vérification en pleine saison tombe sous 100 %, ce
mapping par position bascule vers un mapping par identité (nom résolu en
`canonical_id`) — jamais un retour silencieux à « slot_1 = home ». Les sports
sans domicile (tennis...) n'ont JAMAIS de home/away fictif.
"""

from __future__ import annotations

from .protocol import EventParticipant, RawBookmakerEvent


class UnknownSportRoleMapping(Exception):
    """Aucun mapping slot -> rôle déclaré pour ce sport : on échoue bruyamment
    plutôt que de deviner un rôle (surtout pas un home/away par défaut)."""


# Rôles par slot, déclarés par sport. Ordre = (rôle du slot_1, rôle du slot_2).
# football : empirique ADR-015 (à re-vérifier en pleine saison).
# tennis / tennis de table : ordre arbitraire mais stable, jamais de domicile.
_SLOT_ROLES_BY_SPORT: dict[str, tuple[str, str]] = {
    "football": ("home", "away"),
    # basket/baseball : domicile réel (slot_1 = home Winamax), issue 2-way sans nul.
    "basketball": ("home", "away"),
    "baseball": ("home", "away"),
    # hockey : domicile réel, mais marché RÉGLEMENTAIRE 3-way (nul possible).
    "hockey": ("home", "away"),
    "volleyball": ("home", "away"),
    "american_football": ("home", "away"),
    "tennis": ("player_a", "player_b"),
    "table_tennis": ("player_a", "player_b"),
}


def supported_sports() -> frozenset[str]:
    return frozenset(_SLOT_ROLES_BY_SPORT)


class ParticipantRoleResolver:
    """Résout les slots d'un `RawBookmakerEvent` en `EventParticipant` typés."""

    def resolve(self, event: RawBookmakerEvent) -> list[EventParticipant]:
        if event.is_outright:
            # Un outright (vainqueur d'épreuve) n'a pas deux participants opposés :
            # pas de rôle home/away à en tirer.
            return []

        roles = _SLOT_ROLES_BY_SPORT.get(event.sport)
        if roles is None:
            raise UnknownSportRoleMapping(
                f"Aucun mapping slot->rôle déclaré pour le sport « {event.sport} ». "
                f"Sports connus : {sorted(_SLOT_ROLES_BY_SPORT)}."
            )

        role_1, role_2 = roles
        return [
            EventParticipant(role=role_1, name=event.slot_1_name, bookmaker_slot="slot_1"),
            EventParticipant(role=role_2, name=event.slot_2_name, bookmaker_slot="slot_2"),
        ]
