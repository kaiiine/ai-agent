"""Le score d'un match de tennis, lu sans jamais le compléter.

Un modèle de sets ou de jeux ne peut pas être construit sur `outcome`. Il lui
faut le score, et le score arrive sous forme de texte libre : « 6-3 6-2 »,
« 7-6(5) 6-1 », « 6-7 7-6 1-1 RET », « W/O », « UNK », « 6-4 6-? ».

CE QUE CE MODULE REFUSE DE FAIRE, ET C'EST TOUT SON INTÉRÊT : traiter un abandon
comme un score complet. « 6-2 RET » n'est PAS une victoire 6-2 en deux sets —
c'est un set gagné puis un adversaire qui s'arrête. Compté comme une rencontre
normale, il apprend au modèle que des matchs se gagnent en un set, et il fausse
tout total de jeux et tout total de sets. Mesuré sur le corpus : 4 601 abandons
ATP et 2 824 WTA, plus 2 661 forfaits — soit dix mille rencontres qui, lues
naïvement, sont dix mille scores faux.

CE QUI A ÉTÉ MESURÉ (467 689 rencontres ATP + WTA du corpus embarqué) :

    score absent                117 502   ni score ni sets : rien à lire
    sets lisibles               339 239   dont 51 575 avec au moins un tie-break
    abandon (RET)                 7 425
    forfait (W/O)                 2 661
    disqualification (DEF)           85
    inachevé déclaré                  6
    illisible                       754   « UNK », « &nbsp; », « 6-4 6-? », « 6-4-6-2 »

Aucune de ces catégories n'est jetée : elles sont NOMMÉES. Un score illisible qui
disparaîtrait silencieusement ferait croire à un corpus plus propre qu'il n'est.

LA COMPLÉTUDE EST VÉRIFIÉE CONTRE LE FORMAT. Un best-of-3 se gagne en deux sets,
un best-of-5 en trois. Un score qui n'y arrive pas est INCOMPLET, même si chacun
de ses sets se lit parfaitement — et c'est le cas le plus dangereux, parce qu'il
ne ressemble pas à une erreur.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum

#: Un jeu : « 6-3 », ou « 7-6(5) » quand le set s'est joué au jeu décisif. Le
#: nombre entre parenthèses est le score du PERDANT du tie-break — convention
#: universelle des archives, vérifiée sur 51 575 sets.
_SET = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\((\d{1,2})\))?$")

#: Marqueurs de fin anormale, en minuscules. L'ordre compte : « ret » apparaît
#: dans « retired », et « def » est un mot entier qu'on ne veut pas confondre
#: avec autre chose.
_MARQUEURS = (
    ("w/o", "WALKOVER"), ("walkover", "WALKOVER"), ("walkoer", "WALKOVER"),
    ("ret", "RETIREMENT"), ("retired", "RETIREMENT"),
    ("def", "DEFAULT"), ("disqualified", "DEFAULT"),
    ("unfinished", "UNFINISHED"), ("in progress", "UNFINISHED"),
    ("abandoned", "UNFINISHED"), ("canc", "UNFINISHED"),
)


class StatutScore(str, Enum):
    """Ce qu'on sait de ce score — jamais un booléen « lisible ou non »."""

    COMPLETE = "COMPLETE"          # tous les sets lus, et le format est atteint
    INCOMPLETE = "INCOMPLETE"      # sets lus, mais le vainqueur n'a pas ses sets
    RETIREMENT = "RETIREMENT"      # abandon : le score partiel est réel, le match non
    WALKOVER = "WALKOVER"          # forfait : aucun jeu n'a été joué
    DEFAULT = "DEFAULT"            # disqualification
    UNFINISHED = "UNFINISHED"      # interrompu, déclaré tel quel par la source
    UNREADABLE = "UNREADABLE"      # texte présent, forme non reconnue
    ABSENT = "ABSENT"              # aucun score dans la source

    @property
    def utilisable_pour_un_modele_de_score(self) -> bool:
        """Seul un match ALLÉ AU BOUT décrit une distribution de sets ou de jeux.

        Un abandon porte pourtant un score partiel VRAI : il reste disponible
        pour qui veut l'analyser, mais il ne peut pas entrer dans une population
        de matchs complets sans la fausser.
        """
        return self is StatutScore.COMPLETE


@dataclass(frozen=True)
class SetTennis:
    """Un set. `tiebreak_perdant` vaut `None` quand il n'y a pas eu de jeu décisif."""

    jeux_p1: int
    jeux_p2: int
    tiebreak_perdant: int | None = None

    @property
    def gagnant(self) -> str | None:
        if self.jeux_p1 > self.jeux_p2:
            return "p1"
        if self.jeux_p2 > self.jeux_p1:
            return "p2"
        return None

    @property
    def a_tiebreak(self) -> bool:
        return self.tiebreak_perdant is not None


@dataclass(frozen=True)
class ScoreTennis:
    """Un score lu, avec son statut et ses totaux. Aucun champ n'est complété."""

    statut: StatutScore
    brut: str | None
    sets: tuple[SetTennis, ...] = ()
    best_of: int | None = None
    raison: str = ""

    # -- agrégats, tous dérivés des seuls sets LUS ----------------------------
    @property
    def sets_p1(self) -> int:
        return sum(1 for s in self.sets if s.gagnant == "p1")

    @property
    def sets_p2(self) -> int:
        return sum(1 for s in self.sets if s.gagnant == "p2")

    @property
    def jeux_p1(self) -> int:
        return sum(s.jeux_p1 for s in self.sets)

    @property
    def jeux_p2(self) -> int:
        return sum(s.jeux_p2 for s in self.sets)

    @property
    def total_sets(self) -> int:
        return len(self.sets)

    @property
    def total_jeux(self) -> int:
        return self.jeux_p1 + self.jeux_p2

    @property
    def tiebreaks(self) -> int:
        return sum(1 for s in self.sets if s.a_tiebreak)

    @property
    def vainqueur(self) -> str | None:
        """Le vainqueur DU MATCH d'après les sets, ou rien.

        `None` sur un abandon : le joueur qui menait n'a pas gagné le match au
        score, il l'a gagné parce que l'autre s'est arrêté. Confondre les deux
        ferait apprendre au modèle des victoires en un set et demi.
        """
        if self.statut is not StatutScore.COMPLETE:
            return None
        return "p1" if self.sets_p1 > self.sets_p2 else "p2"

    @property
    def utilisable(self) -> bool:
        return self.statut.utilisable_pour_un_modele_de_score


def _sets_requis(best_of: int | None) -> int | None:
    """Sets nécessaires pour gagner. `None` quand le format est inconnu — on ne
    suppose pas best-of-3 par défaut : 17 435 matchs ATP se jouent en cinq."""
    if not best_of or best_of < 1:
        return None
    return math.ceil(best_of / 2)


def _marqueur(texte: str) -> str | None:
    bas = texte.lower()
    for motif, statut in _MARQUEURS:
        if re.search(rf"(?<![a-z]){re.escape(motif)}", bas):
            return statut
    return None


def _lire_sets(morceaux) -> tuple[tuple[SetTennis, ...], bool]:
    """Les sets lus, et si TOUS l'ont été. Un seul morceau illisible suffit à
    disqualifier l'ensemble : un score partiellement lu est un score inventé pour
    la partie qu'on n'a pas lue."""
    sets = []
    for morceau in morceaux:
        trouve = _SET.match(morceau)
        if not trouve:
            return tuple(sets), False
        p1, p2, tb = trouve.groups()
        sets.append(SetTennis(int(p1), int(p2), int(tb) if tb is not None else None))
    return tuple(sets), True


def parser_score(brut: str | None, *, best_of: int | None = None,
                 comment: str | None = None) -> ScoreTennis:
    """Texte de score -> `ScoreTennis`. Ne complète jamais, ne devine jamais.

    `comment` est consulté APRÈS le score, et seulement pour confirmer une fin
    anormale que le score ne dit pas : les archives portent parfois « Retired »
    en commentaire d'un score qui paraît complet. Le commentaire ne peut que
    DÉGRADER le statut, jamais le promouvoir — une source qui dit « Completed »
    sur un score illisible ne le rend pas lisible.
    """
    if brut is None or not str(brut).strip():
        return ScoreTennis(StatutScore.ABSENT, brut, best_of=best_of,
                           raison="aucun score dans la source")

    texte = str(brut).strip()
    statut_marqueur = _marqueur(texte)
    morceaux = [m for m in texte.split() if _marqueur(m) is None]
    sets, tout_lu = _lire_sets(morceaux)

    if statut_marqueur == "WALKOVER":
        return ScoreTennis(StatutScore.WALKOVER, brut, sets, best_of,
                           "forfait : aucun jeu n'a été joué")
    if statut_marqueur in ("RETIREMENT", "DEFAULT", "UNFINISHED"):
        statut = StatutScore[statut_marqueur]
        return ScoreTennis(statut, brut, sets if tout_lu else (), best_of,
                           f"{statut.value.lower()} — le score partiel est réel, "
                           "le match n'est pas allé à son terme")

    if not sets or not tout_lu:
        return ScoreTennis(StatutScore.UNREADABLE, brut, (), best_of,
                           f"forme non reconnue : {texte[:40]!r}")

    # Le commentaire ne DÉGRADE que ce qui paraît complet.
    commentaire = (comment or "").strip().lower()
    if commentaire.startswith("retir"):
        return ScoreTennis(StatutScore.RETIREMENT, brut, sets, best_of,
                           "abandon déclaré par le commentaire de la source")
    if commentaire.startswith("walko"):
        return ScoreTennis(StatutScore.WALKOVER, brut, sets, best_of,
                           "forfait déclaré par le commentaire de la source")

    requis = _sets_requis(best_of)
    provisoire = ScoreTennis(StatutScore.COMPLETE, brut, sets, best_of)
    if requis is None:
        return ScoreTennis(StatutScore.INCOMPLETE, brut, sets, best_of,
                           "format (best_of) inconnu : la complétude n'est pas vérifiable")
    if max(provisoire.sets_p1, provisoire.sets_p2) != requis:
        return ScoreTennis(
            StatutScore.INCOMPLETE, brut, sets, best_of,
            f"aucun joueur n'atteint {requis} set(s) gagnant(s) sur un best-of-{best_of} "
            f"({provisoire.sets_p1}-{provisoire.sets_p2}) : le match n'est pas à son terme")
    return provisoire


@dataclass(frozen=True)
class CouvertureScores:
    """Ce qu'un corpus donne réellement à lire, catégorie par catégorie."""

    total: int = 0
    par_statut: dict = None            # type: ignore[assignment]
    exemples: dict = None              # type: ignore[assignment]

    @property
    def utilisables(self) -> int:
        return (self.par_statut or {}).get(StatutScore.COMPLETE.value, 0)

    @property
    def taux_utilisable(self) -> float | None:
        """`None` si rien n'a été parcouru — jamais 0 %, qui serait une mesure."""
        return round(self.utilisables / self.total, 4) if self.total else None


def mesurer_couverture(matchs) -> CouvertureScores:
    """Passe un corpus au parseur et compte, sans rien écarter."""
    from collections import Counter

    par_statut: Counter = Counter()
    exemples: dict[str, str] = {}
    total = 0
    for m in matchs:
        total += 1
        lu = parser_score(getattr(m, "score", None), best_of=getattr(m, "best_of", None),
                          comment=getattr(m, "comment", None))
        par_statut[lu.statut.value] += 1
        exemples.setdefault(lu.statut.value, repr(lu.brut))
    return CouvertureScores(total, dict(par_statut.most_common()), exemples)
