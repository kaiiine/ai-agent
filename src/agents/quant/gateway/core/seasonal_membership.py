"""Appartenance d'une équipe à une compétition, à une saison donnée.

L'identité d'une équipe et son appartenance à une compétition étaient la même
chose : `LEAGUE_TEAMS` associe une compétition à une liste d'équipes, sans
saison, et les 188 entités portent toutes `valid_from = None`. Conséquence
silencieuse : au prochain cycle promotion/relégation, les promus n'existent plus
pour la résolution — sans erreur, sans trace.

DEUX NOTIONS, DEUX OBJETS.
    `team:football:eng:leeds` est la MÊME entité en Premier League et en
    Championship. Descendre n'est pas devenir un autre club — fabriquer une
    seconde identité couperait l'historique en deux au pire moment.
    L'appartenance, elle, est une relation DATÉE, et il peut y en avoir
    plusieurs à la fois : un club joue son championnat, sa coupe nationale et
    sa coupe d'Europe la même semaine.

TROIS RÉPONSES, PAS DEUX.
    `NOT_ACTIVE` affirme que le club ne joue pas cette compétition cette
    saison-là. `UNKNOWN` dit qu'on n'en sait rien. Les confondre transforme un
    trou de données en démenti : c'est ainsi qu'une identité correcte se fait
    rejeter, et c'est l'erreur exacte que ce module refuse de commettre.

PREUVE PLUTÔT QUE DÉCLARATION.
    Une appartenance se DÉDUIT des rencontres réellement observées : un club qui
    a joué dans cette compétition cette saison-là y appartenait. Aucune liste à
    tenir à jour à la main, donc aucune liste à oublier de mettre à jour.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"          # observé : le club a joué cette compétition cette saison
    NOT_ACTIVE = "NOT_ACTIVE"  # la saison est connue, le club n'y figure pas
    UNKNOWN = "UNKNOWN"        # aucune donnée sur cette compétition/saison


@dataclass(frozen=True)
class Membership:
    """Participation observée d'une équipe à une compétition, sur une saison."""

    team_id: str
    competition_id: str
    season: str
    first_seen: date
    last_seen: date
    matches_observed: int
    source: str = "observed_matches"

    def couvre(self, jour: date) -> bool:
        """Une coupe se joue par fenêtres : la participation vaut de la première
        à la dernière rencontre observée, bornes comprises."""
        return self.first_seen <= jour <= self.last_seen


class SeasonalMembershipRegistry:
    """Qui jouait quoi, quand. Construit depuis des rencontres canoniques.

    Ne contient AUCUNE identité d'équipe : celles-ci vivent dans le référentiel
    d'identités et ne changent pas quand un club monte ou descend.
    """

    def __init__(self) -> None:
        self._par_cle: dict[tuple[str, str, str], Membership] = {}
        #: (competition, season) où des rencontres ont été observées.
        self._saisons_connues: set[tuple[str, str]] = set()
        #: (competition, season) dont l'EFFECTIF est réputé complet. Seules
        #: celles-ci autorisent un `NOT_ACTIVE`.
        #:
        #: Sans cette seconde liste, une seule rencontre ingérée suffisait à
        #: déclarer « connue » toute une saison, et donc à répondre NOT_ACTIVE
        #: pour les dix-neuf autres clubs. Une compétition à moitié chargée
        #: produisait alors de faux démentis — précisément le rejet d'identités
        #: correctes que ce module existe pour empêcher.
        self._effectifs_complets: set[tuple[str, str]] = set()

    # ── Alimentation ────────────────────────────────────────────────────────
    def ingest_matches(self, matches) -> int:
        """Déduit les appartenances des rencontres. Rend le nombre d'entrées."""
        agrege: dict[tuple[str, str, str], list[date]] = defaultdict(list)
        for m in matches:
            jour = m.kickoff.date() if isinstance(m.kickoff, datetime) else m.kickoff
            self._saisons_connues.add((m.league_id, m.season))
            for equipe in (m.home_team_id, m.away_team_id):
                agrege[(equipe, m.league_id, m.season)].append(jour)

        for (equipe, competition, saison), jours in agrege.items():
            cle = (equipe, competition, saison)
            existant = self._par_cle.get(cle)
            premier = min(jours) if existant is None else min(existant.first_seen, min(jours))
            dernier = max(jours) if existant is None else max(existant.last_seen, max(jours))
            deja = existant.matches_observed if existant else 0
            self._par_cle[cle] = Membership(
                team_id=equipe, competition_id=competition, season=saison,
                first_seen=premier, last_seen=dernier,
                matches_observed=deja + len(jours))
        return len(self._par_cle)

    def declare(self, membership: Membership) -> None:
        """Appartenance posée à la main — pour ce qu'aucune rencontre n'atteste
        encore (calendrier annoncé, tirage au sort connu). La source la distingue
        d'une observation, et rien ne les fond."""
        self._par_cle[(membership.team_id, membership.competition_id,
                       membership.season)] = membership
        self._saisons_connues.add((membership.competition_id, membership.season))

    # ── Interrogation ───────────────────────────────────────────────────────
    def membership(self, team_id: str, competition_id: str,
                   season: str) -> MembershipStatus:
        """ACTIVE / NOT_ACTIVE / UNKNOWN — jamais déduit du nom de l'équipe.

        La question porte sur la SAISON, pas sur un jour : un club éliminé en
        novembre a bien participé à l'édition. Pour savoir s'il jouait encore à
        une date donnée, c'est `Membership.couvre` qu'il faut lire — deux
        questions distinctes, et les fondre ferait répondre « non » à la
        première pour cause de calendrier.
        """
        if (team_id, competition_id, season) in self._par_cle:
            return MembershipStatus.ACTIVE
        if (competition_id, season) in self._effectifs_complets:
            return MembershipStatus.NOT_ACTIVE
        return MembershipStatus.UNKNOWN

    def memberships_of(self, team_id: str, season: str) -> tuple[Membership, ...]:
        """TOUTES les compétitions d'un club sur une saison. Un club en joue
        plusieurs à la fois ; n'en rendre qu'une choisirait à sa place."""
        return tuple(sorted(
            (m for (t, _c, s), m in self._par_cle.items() if t == team_id and s == season),
            key=lambda m: m.competition_id))

    def teams_of(self, competition_id: str, season: str) -> tuple[str, ...]:
        return tuple(sorted(
            m.team_id for (_t, c, s), m in self._par_cle.items()
            if c == competition_id and s == season))

    def seasons_of(self, team_id: str) -> tuple[str, ...]:
        return tuple(sorted({s for (t, _c, s) in self._par_cle if t == team_id}))

    def mark_roster_complete(self, competition_id: str, season: str) -> None:
        """Déclare l'effectif de cette saison COMPLET — et donc un démenti permis.

        À n'appeler que par un chargement qui a vraiment tout ingéré. C'est la
        seule porte vers `NOT_ACTIVE` : par défaut, ce qui n'a pas été vu reste
        `UNKNOWN`, et aucune rencontre correcte n'est rejetée par ignorance.
        """
        self._effectifs_complets.add((competition_id, season))

    def knows(self, competition_id: str, season: str) -> bool:
        """Des rencontres ont-elles été observées pour cette compétition/saison ?"""
        return (competition_id, season) in self._saisons_connues

    def roster_is_complete(self, competition_id: str, season: str) -> bool:
        return (competition_id, season) in self._effectifs_complets

    def __len__(self) -> int:
        return len(self._par_cle)
