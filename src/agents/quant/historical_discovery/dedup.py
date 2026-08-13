"""La même rencontre vue par deux sources ne compte qu'une fois — tous sports.

Généralise `betting_engine/acquisition/reconciliation.py`, qui rend le même
service pour le football et reste la référence de l'algorithme : clé
(compétition, paire non ordonnée), séparation temporelle APRÈS regroupement,
conflit rapporté jamais arbitré. La constante de tolérance football est importée
de là plutôt que recopiée — deux valeurs qui divergeraient produiraient deux
comptes d'échantillon selon le chemin emprunté.

CE QUI CHANGE AVEC LE SPORT, C'EST LE TEMPS. Six heures séparent proprement un
match aller d'un match retour en football. Elles fusionneraient les deux
manches d'un *doubleheader* de baseball, jouées le même après-midi entre les
mêmes équipes — deux rencontres distinctes réduites à une. À l'inverse, un match
de tennis reporté par la pluie reste la même rencontre à deux jours d'écart.
La tolérance est donc une propriété du sport, déclarée et justifiée.

L'IDENTIFIANT DE SOURCE PASSE AVANT LE TEMPS. Deux lignes portant le même
`(source, source_event_id)` sont la même rencontre par construction, quelle que
soit la date : c'est le seul rapprochement qui ne peut pas se tromper.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum

from src.agents.quant.betting_engine.acquisition.reconciliation import (
    TOLERANCE_HEURES as TOLERANCE_FOOTBALL,
)


class DedupStatus(str, Enum):
    UNIQUE = "UNIQUE"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    UNRESOLVED = "UNRESOLVED"


#: Tolérance d'appariement, en heures, par sport. Chaque valeur répond à une
#: question précise : quel écart sépare encore DEUX rencontres réelles ?
TOLERANCES_HEURES: dict[str, int] = {
    # Aller/retour jamais le même jour ; deux sources décalent d'un fuseau.
    "football": TOLERANCE_FOOTBALL,
    # Reports pour pluie : la même rencontre peut glisser de deux jours.
    "tennis": 48,
    # *Doubleheader* : deux rencontres le même jour, ~5 h d'écart. Au-delà de 4 h,
    # on les fondrait en une et on perdrait une observation réelle.
    "baseball": 4,
    "basketball": 12,
    "hockey": 12,
    "american_football": 12,
    "volleyball": 12,
}

#: Sport inconnu : la tolérance la plus PRUDENTE, celle qui sépare le plus.
#: Fusionner à tort détruit une observation ; séparer à tort en garde deux, et
#: cela se voit dans les comptes.
TOLERANCE_PAR_DEFAUT = 4


def tolerance_pour(sport: str) -> int:
    return TOLERANCES_HEURES.get(sport, TOLERANCE_PAR_DEFAUT)


@dataclass(frozen=True)
class Conflit:
    """Deux sources, une rencontre, deux issues. Rapporté, jamais arbitré."""

    sport: str
    competition: str
    participants: tuple[str, ...]
    scheduled_at: str
    versions: tuple[tuple[str, str, str], ...]   # (source, outcome, score)


@dataclass(frozen=True)
class DedupResult:
    uniques: tuple = ()
    duplicates: int = 0
    conflicts: tuple[Conflit, ...] = ()
    unresolved: tuple = ()
    par_source: dict[str, int] = field(default_factory=dict)

    @property
    def resume(self) -> dict:
        return {
            "raw_par_source": dict(self.par_source),
            "raw_total": sum(self.par_source.values()),
            "unique": len(self.uniques),
            "duplicates": self.duplicates,
            "conflicts": len(self.conflicts),
            "unresolved": len(self.unresolved),
        }

    @property
    def conservation_ok(self) -> bool:
        """Chaque ligne brute doit se retrouver quelque part. Sans ce contrôle,
        une observation perdue en route ressemble à un dédoublonnage réussi."""
        lignes_en_conflit = sum(len(c.versions) for c in self.conflicts)
        return sum(self.par_source.values()) == (
            len(self.uniques) + self.duplicates + lignes_en_conflit
            + len(self.unresolved))


def _cle_participants(participants: tuple[str, ...]) -> tuple[str, ...]:
    """Paire NON ORDONNÉE : une source peut inverser domicile et extérieur, ou
    les deux côtés d'un tableau de tennis."""
    return tuple(sorted(participants))


def _empreinte(e, participants: tuple[str, ...]) -> tuple:
    """Compétition + participants, SANS horaire.

    L'horodatage n'entre pas dans la clé : arrondi, il annule la tolérance
    (19 h 00 et 21 h 00 tombent dans deux seaux et ne se comparent jamais) ;
    exact, il n'apparie plus rien. Le temps ne sépare qu'ensuite.
    """
    return (e.competition, _cle_participants(participants))


def dedupliquer(evidences, *, sport: str, participants_de=None) -> DedupResult:
    """Fusionne des observations venues de plusieurs sources.

    `participants_de` rend les identités CANONIQUES d'une observation, ou None
    si elles ne sont pas résolues — auquel cas l'observation part en
    `UNRESOLVED` plutôt que d'être appariée sur des identifiants de sources
    différentes, ce qui n'apparierait jamais rien tout en ayant l'air de
    fonctionner. Par défaut, les participants bruts servent tels quels (cas d'une
    source unique déjà normalisée).
    """
    if participants_de is None:
        def participants_de(e):
            return tuple(e.participants)

    tolerance = timedelta(hours=tolerance_pour(sport))
    par_source: dict[str, int] = defaultdict(int)
    groupes: dict[tuple, list] = defaultdict(list)
    non_resolus: list = []
    #: Même (source, source_event_id) vu deux fois : doublon certain, sans date.
    vus: set[tuple[str, str]] = set()
    doublons_par_id = 0

    for e in evidences:
        par_source[e.source] += 1
        if e.stable_key in vus:
            doublons_par_id += 1
            continue
        vus.add(e.stable_key)
        ids = participants_de(e)
        if ids is None or any(i is None for i in ids):
            non_resolus.append(e)
            continue
        groupes[_empreinte(e, tuple(ids))].append((tuple(ids), e))

    uniques, conflits = [], []
    doublons = doublons_par_id
    for entrees in groupes.values():
        for grappe in _regrouper_par_proximite(entrees, tolerance):
            sources = {e.source for _ids, e in grappe}
            issues = {(e.outcome, e.score) for _ids, e in grappe}
            if len(sources) > 1 and len({o for o, _s in issues}) > 1:
                ids0, e0 = grappe[0]
                conflits.append(Conflit(
                    sport=sport, competition=e0.competition,
                    participants=_cle_participants(ids0),
                    scheduled_at=e0.scheduled_at.isoformat(),
                    versions=tuple(sorted(
                        (e.source, e.outcome or "", e.score or "")
                        for _ids, e in grappe))))
                continue
            doublons += len(grappe) - 1
            uniques.append(grappe[0][1])

    uniques.sort(key=lambda e: e.scheduled_at)
    return DedupResult(tuple(uniques), doublons, tuple(conflits),
                       tuple(non_resolus), dict(par_source))


def _regrouper_par_proximite(entrees, tolerance: timedelta) -> list[list]:
    """Sépare des rencontres de même empreinte mais trop éloignées dans le temps.

    La comparaison se fait au PREMIER de la grappe, pas au précédent : de proche
    en proche, une série de rencontres espacées d'un peu moins que la tolérance
    finirait toutes fondues, quel que soit l'écart total.
    """
    ordonnees = sorted(entrees, key=lambda x: x[1].scheduled_at)
    grappes: list[list] = []
    for entree in ordonnees:
        if grappes and (entree[1].scheduled_at - grappes[-1][0][1].scheduled_at
                        <= tolerance):
            grappes[-1].append(entree)
        else:
            grappes.append([entree])
    return grappes
