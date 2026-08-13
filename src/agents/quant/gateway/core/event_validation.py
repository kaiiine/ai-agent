"""Une identité d'événement doit être cohérente avec qui joue quoi.

Le garde de provenance attrape un identifiant d'ÉVÉNEMENT inventé, parce que le
scan en fournit la liste exhaustive. Il ne voyait pas ceci :

    competition:football:eng:premier_league  home=psg  away=aston_villa

Chaque morceau existe. L'assemblage est faux — le PSG ne joue pas en Premier
League — et aucun contrôle structurel ne pouvait le dire tant que rien ne savait
QUI joue QUOI. Le référentiel saisonnier le sait désormais.

RÈGLE : on ne rejette que sur une CONTRADICTION établie. Un club dont
l'appartenance est `UNKNOWN` n'est pas un club en faute — c'est un trou de
données, et le confondre avec un démenti rejetterait des rencontres correctes,
ce qui est exactement le défaut qu'on répare.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .seasonal_membership import MembershipStatus, SeasonalMembershipRegistry


class ValidationStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    COMPETITION_MEMBERSHIP_MISMATCH = "COMPETITION_MEMBERSHIP_MISMATCH"
    MEMBERSHIP_UNKNOWN = "MEMBERSHIP_UNKNOWN"


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    competition_id: str
    season: str
    #: Participants dont l'appartenance CONTREDIT la compétition annoncée.
    offending: tuple[str, ...] = ()
    #: Participants dont l'appartenance est inconnue — jamais comptés comme fautifs.
    unknown: tuple[str, ...] = ()
    detail: str = ""

    @property
    def rejected(self) -> bool:
        return self.status is ValidationStatus.COMPETITION_MEMBERSHIP_MISMATCH


def valider_appartenance(
    registry: SeasonalMembershipRegistry,
    *,
    competition_id: str,
    season: str,
    participant_ids,
) -> ValidationResult:
    """Les participants annoncés jouent-ils réellement cette compétition ?

    Ne se prononce QUE sur ce que le référentiel sait. Sans données sur la
    compétition/saison, la réponse est `MEMBERSHIP_UNKNOWN` : ni un feu vert, ni
    un rejet.
    """
    participants = tuple(participant_ids or ())
    if not participants:
        return ValidationResult(
            ValidationStatus.MEMBERSHIP_UNKNOWN, competition_id, season,
            detail="aucun participant fourni")

    # Un démenti exige un effectif RÉPUTÉ COMPLET. Une saison à moitié chargée
    # ferait passer dix-neuf clubs sur vingt pour des intrus.
    if not registry.roster_is_complete(competition_id, season):
        confirmes = tuple(
            p for p in participants
            if registry.membership(p, competition_id, season) is MembershipStatus.ACTIVE)
        if len(confirmes) == len(participants):
            return ValidationResult(ValidationStatus.CONSISTENT, competition_id, season)
        return ValidationResult(
            ValidationStatus.MEMBERSHIP_UNKNOWN, competition_id, season,
            unknown=tuple(p for p in participants if p not in confirmes),
            detail=(f"effectif de {competition_id} saison {season} non réputé "
                    f"complet — ni confirmation ni démenti"))

    fautifs, inconnus = [], []
    for participant in participants:
        statut = registry.membership(participant, competition_id, season)
        if statut is MembershipStatus.NOT_ACTIVE:
            fautifs.append(participant)
        elif statut is MembershipStatus.UNKNOWN:
            inconnus.append(participant)

    if fautifs:
        return ValidationResult(
            ValidationStatus.COMPETITION_MEMBERSHIP_MISMATCH, competition_id, season,
            offending=tuple(fautifs), unknown=tuple(inconnus),
            detail=(f"{', '.join(fautifs)} ne participe(nt) pas à {competition_id} "
                    f"en {season} — l'identité annoncée est impossible"))

    if inconnus:
        return ValidationResult(
            ValidationStatus.MEMBERSHIP_UNKNOWN, competition_id, season,
            unknown=tuple(inconnus),
            detail=f"appartenance inconnue pour {', '.join(inconnus)}")

    return ValidationResult(ValidationStatus.CONSISTENT, competition_id, season)
