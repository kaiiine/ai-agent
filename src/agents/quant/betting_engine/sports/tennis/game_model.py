"""Tennis — modèles de JEUX et de SETS, dérivés du score et non du vainqueur.

L'Elo moneyline tennis répond à « qui gagne le match ». La probabilité qu'un
match dure trois sets, ou qu'il s'y joue plus de 22 jeux, n'est PAS contenue dans
ce nombre : deux joueurs à 0,62 / 0,38 peuvent se rencontrer en deux sets secs ou
en trois sets accrochés, et le moneyline ne les distingue pas. Recycler sa
probabilité pour ces marchés serait inventer la quantité manquante.

L'ORDRE DES JOUEURS EST CANONIQUE, ET C'EST VITAL. Le corpus range le VAINQUEUR
en premier : `outcome` vaut « p1 » sur les 227 933 rencontres ATP, sans
exception. Un modèle qui traiterait p1 et p2 comme deux camps apprendrait que
« p1 gagne toujours » — une fuite parfaite, un Brier de zéro, et une prédiction
sans aucune valeur. Les deux joueurs sont donc rangés par leur nom canonique,
comme le fait déjà l'Elo du même sport, et le score est réordonné avec eux.

CE QUI CONSTRUIT ET CE QUI ÉVALUE NE SONT PAS LA MÊME POPULATION. Challengers,
qualifications et Futures bâtissent la force des joueurs mais ne sont jamais des
cibles : AXON ne parie que le circuit principal, et évaluer sur un marché que le
bookmaker n'expose pas fausserait la couverture dans les deux sens. C'est la
règle déjà appliquée par l'Elo, reprise telle quelle.

LA HIÉRARCHIE EST DÉCLARÉE, PAS SUPPOSÉE. Des jeux on dérive les sets, et des
sets le format. Chaque étape fait une hypothèse d'indépendance qu'il faut dire :
les jeux d'un set ne sont pas indépendants (le service alterne, le score compte),
et les sets d'un match non plus. Ces approximations sont exactement ce que le
benchmark doit sanctionner ou valider — elles ne sont pas défendues ici.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .score_parser import StatutScore, parser_score


@dataclass(frozen=True)
class RencontreTennis:
    """Une rencontre lue, rangée dans l'ordre CANONIQUE des joueurs."""

    match_id: str
    date: object
    joueur_a: str                 # premier dans l'ordre canonique — jamais le vainqueur
    joueur_b: str
    jeux_a: int
    jeux_b: int
    sets_a: int
    sets_b: int
    best_of: int
    cible: bool                   # rencontre à cotes du circuit principal
    #: Niveau DÉCLARÉ par la source (« tour », « challenger_qualifying », …). Il
    #: n'est pas redondant avec `cible` : mesuré, les 70 688 cibles ATP n'ont
    #: AUCUN score, et les 151 873 rencontres scorées ne sont jamais des cibles.
    #: Un modèle de score s'évalue donc sur le NIVEAU, pas sur le drapeau de cote.
    niveau: str | None = None
    surface: str | None = None
    #: Vainqueur du PREMIER set (« a » / « b »). C'est le marché « Vainqueur du
    #: 1er set », et il ne se confond pas avec la majorité des jeux : un joueur
    #: peut perdre le premier set et gagner plus de jeux sur la rencontre.
    premier_set: str | None = None

    @property
    def total_jeux(self) -> int:
        return self.jeux_a + self.jeux_b

    @property
    def total_sets(self) -> int:
        return self.sets_a + self.sets_b

    @property
    def vainqueur(self) -> str:
        return "a" if self.sets_a > self.sets_b else "b"


def _premier_set(lu, a_est_le_gagnant: bool) -> str | None:
    """Le vainqueur du premier set, replacé dans l'ordre canonique."""
    if not lu.sets:
        return None
    gagnant = lu.sets[0].gagnant
    if gagnant is None:
        return None
    if a_est_le_gagnant:
        return "a" if gagnant == "p1" else "b"
    return "b" if gagnant == "p1" else "a"


def rencontres_lisibles(matchs) -> list[RencontreTennis]:
    """Corpus brut -> rencontres COMPLÈTES, rangées canoniquement.

    Tout ce qui n'est pas allé à son terme est écarté ici, une fois pour toutes :
    un abandon porte un score partiel vrai, mais il ne décrit aucune distribution
    de sets ni de jeux.
    """
    sorties: list[RencontreTennis] = []
    for m in matchs:
        lu = parser_score(getattr(m, "score", None), best_of=getattr(m, "best_of", None),
                          comment=getattr(m, "comment", None))
        if lu.statut is not StatutScore.COMPLETE:
            continue
        gagnant, perdant = m.p1_name, m.p2_name
        if gagnant is None or perdant is None:
            continue
        # Ordre canonique par NOM — indépendant de l'issue, donc sans fuite.
        a_est_le_gagnant = gagnant < perdant
        a, b = (gagnant, perdant) if a_est_le_gagnant else (perdant, gagnant)
        jeux_a, jeux_b = ((lu.jeux_p1, lu.jeux_p2) if a_est_le_gagnant
                          else (lu.jeux_p2, lu.jeux_p1))
        sets_a, sets_b = ((lu.sets_p1, lu.sets_p2) if a_est_le_gagnant
                          else (lu.sets_p2, lu.sets_p1))
        sorties.append(RencontreTennis(
            match_id=f"{m.tourney_id}:{m.round}:{gagnant}:{perdant}",
            date=m.tourney_date, joueur_a=a, joueur_b=b,
            jeux_a=jeux_a, jeux_b=jeux_b, sets_a=sets_a, sets_b=sets_b,
            best_of=lu.best_of or 3,
            cible=bool(getattr(m, "est_cible_d_evaluation", False)),
            niveau=getattr(m, "circuit", None),
            surface=getattr(m, "surface", None),
            premier_set=_premier_set(lu, a_est_le_gagnant)))
    return sorties


# ── Force en JEUX, séquentielle ──────────────────────────────────────────────

@dataclass(frozen=True)
class ParamsJeux:
    """Paramètres de méthode, fixes et documentés."""

    force_initiale: float = 0.0      # écart nul : aucun joueur n'est favori a priori
    k: float = 0.06                  # pas d'apprentissage sur la PART de jeux
    min_matchs: int = 20             # sous ce seuil, la force vaut son initialisation
    min_residus: int = 200
    notes: str = ""


@dataclass(frozen=True)
class PredictionJeux:
    """Ce que le modèle annonce avant la rencontre."""

    part_jeux_a: float               # part attendue des jeux pour le joueur A
    total_attendu: float             # nombre de jeux attendu dans la rencontre
    total_sigma: float
    p_jeu_a: float                   # probabilité que A gagne UN jeu donné
    matchs_a: int
    matchs_b: int
    #: Moyenne de ligue du format, CONSERVÉE pour comparaison. C'est la
    #: prédiction que ferait un modèle sans information sur l'affiche.
    total_moyen_ligue: float | None = None


class ForcesEnJeux:
    """Force de chaque joueur, exprimée en PART DE JEUX gagnés.

    Séquentielle et sans fuite : la force d'un joueur au moment T ne dépend que
    de ses rencontres strictement antérieures. La mise à jour porte sur l'écart
    entre la part observée et la part attendue, comme un Elo dont l'issue serait
    continue plutôt que binaire.
    """

    def __init__(self, params: ParamsJeux):
        self.params = params
        self.force: dict[str, float] = {}
        self.joues: dict[str, int] = {}
        #: Somme et somme des carrés des totaux de jeux — jamais la liste. La
        #: variance recalculée sur tout l'historique à chaque prédiction coûte un
        #: temps quadratique : sur les 172 096 rencontres WTA, le rejeu ne
        #: terminait pas.
        self._n_totaux = 0
        self._somme = 0.0
        self._somme_carres = 0.0
        #: Somme et effectif des totaux de jeux PAR FORMAT, tenus au fil de
        #: l'eau. Rebâtir la liste à chaque mise à jour coûterait un temps
        #: quadratique sur un corpus de 339 000 rencontres, pour la même moyenne.
        self._somme_par_format: dict[int, float] = {}
        self._n_par_format: dict[int, int] = {}

    def _part_attendue(self, a: str, b: str) -> float:
        ecart = self.force.get(a, self.params.force_initiale) - \
            self.force.get(b, self.params.force_initiale)
        return 1.0 / (1.0 + math.exp(-ecart))

    def _sigma_total(self) -> float | None:
        n = self._n_totaux
        if n < self.params.min_residus:
            return None
        moyenne = self._somme / n
        variance = (self._somme_carres - n * moyenne * moyenne) / (n - 1)
        return math.sqrt(variance) if variance > 0 else None

    def _total_moyen(self, best_of: int) -> float | None:
        """Nombre de jeux moyen, PAR FORMAT. Un best-of-5 n'a pas la même durée
        qu'un best-of-3 : les mélanger produirait un total attendu qui ne décrit
        aucun des deux."""
        n = self._n_par_format.get(best_of, 0)
        if n < self.params.min_residus:
            return None
        return self._somme_par_format[best_of] / n

    def predict(self, a: str, b: str, best_of: int) -> PredictionJeux | None:
        na, nb = self.joues.get(a, 0), self.joues.get(b, 0)
        if min(na, nb) < self.params.min_matchs:
            return None
        sigma = self._sigma_total()
        moyenne = self._total_moyen(best_of)
        if sigma is None or moyenne is None:
            return None
        part = self._part_attendue(a, b)
        # Le total attendu est celui de CETTE affiche, dérivé de la force
        # relative : deux joueurs proches jouent plus de jeux que deux joueurs
        # déséquilibrés. La moyenne de ligue ne dit rien de cet écart — mesuré,
        # elle rendait une prédiction identique pour toutes les rencontres, donc
        # exactement la baseline.
        return PredictionJeux(
            part_jeux_a=part, total_attendu=esperance_jeux_match(part, best_of),
            total_sigma=sigma, p_jeu_a=part, matchs_a=na, matchs_b=nb,
            total_moyen_ligue=moyenne)

    def update(self, r: RencontreTennis) -> None:
        attendue = self._part_attendue(r.joueur_a, r.joueur_b)
        observee = r.jeux_a / r.total_jeux if r.total_jeux else 0.5
        ajustement = self.params.k * (observee - attendue)
        self.force[r.joueur_a] = self.force.get(
            r.joueur_a, self.params.force_initiale) + ajustement
        self.force[r.joueur_b] = self.force.get(
            r.joueur_b, self.params.force_initiale) - ajustement
        self.joues[r.joueur_a] = self.joues.get(r.joueur_a, 0) + 1
        self.joues[r.joueur_b] = self.joues.get(r.joueur_b, 0) + 1
        total = float(r.total_jeux)
        self._n_totaux += 1
        self._somme += total
        self._somme_carres += total * total
        self._somme_par_format[r.best_of] = (
            self._somme_par_format.get(r.best_of, 0.0) + float(r.total_jeux))
        self._n_par_format[r.best_of] = self._n_par_format.get(r.best_of, 0) + 1


# ── Des jeux aux sets ────────────────────────────────────────────────────────

def p_set(p_jeu: float) -> float:
    """Probabilité de gagner UN set, à partir de la probabilité de gagner un jeu.

    HYPOTHÈSE DÉCLARÉE : les jeux sont indépendants et de même probabilité. Elle
    est FAUSSE dans le détail — le service alterne, et un joueur mène ou court
    après le score — mais elle est la seule dérivation possible sans données
    point par point, que le corpus ne contient pas. Le benchmark dit ce qu'elle
    vaut ; ce module ne la défend pas.

    Un set se gagne à six jeux avec deux d'écart, ou au jeu décisif à 6-6. Le
    jeu décisif est traité comme un jeu de plus : c'est une approximation, et
    elle est nommée.
    """
    p = min(max(p_jeu, 1e-6), 1 - 1e-6)
    q = 1.0 - p

    def combinaison(n, k):
        return math.comb(n, k)

    # Gagné 6-0 à 6-4 : six jeux gagnés, k perdus, le dernier étant gagné.
    total = sum(combinaison(5 + k, k) * p ** 6 * q ** k for k in range(5))
    # 5-5 atteint, puis 7-5 ou tie-break.
    p_5_5 = combinaison(10, 5) * p ** 5 * q ** 5
    total += p_5_5 * (p * p + 2 * p * q * p)     # 7-5, ou 6-6 puis tie-break gagné
    return min(1.0, total)


def distribution_jeux_set(p_jeu: float) -> dict[tuple[int, int], float]:
    """Distribution du SCORE EN JEUX d'un set, du point de vue de A.

    Même hypothèse déclarée que `p_set` — jeux indépendants et équiprobables — et
    même construction combinatoire. Elle sert à obtenir une espérance de jeux PAR
    RENCONTRE, ce qu'aucune moyenne de ligue ne peut donner : deux joueurs de
    force égale jouent plus de jeux que deux joueurs déséquilibrés, et c'est
    exactement ce que cote un total de jeux.
    """
    p = min(max(p_jeu, 1e-6), 1 - 1e-6)
    q = 1.0 - p
    scores: dict[tuple[int, int], float] = {}
    for k in range(5):                       # 6-0 … 6-4, et leurs miroirs
        masse = math.comb(5 + k, k) * p ** 6 * q ** k
        scores[(6, k)] = masse
        scores[(k, 6)] = math.comb(5 + k, k) * q ** 6 * p ** k
    p_5_5 = math.comb(10, 5) * p ** 5 * q ** 5
    scores[(7, 5)] = p_5_5 * p * p           # A prend les deux jeux suivants
    scores[(5, 7)] = p_5_5 * q * q
    reste = p_5_5 * 2 * p * q                # 6-6 : jeu décisif
    scores[(7, 6)] = reste * p
    scores[(6, 7)] = reste * q
    return scores


def esperance_jeux_par_set(p_jeu: float) -> float:
    d = distribution_jeux_set(p_jeu)
    masse = sum(d.values())
    if masse <= 0:
        return 0.0
    return sum((a + b) * m for (a, b), m in d.items()) / masse


def esperance_jeux_match(p_jeu: float, best_of: int) -> float:
    """Jeux attendus dans la RENCONTRE : sets attendus × jeux attendus par set."""
    sets_attendus = sum(int(n) * m for n, m in total_sets(p_set(p_jeu), best_of).items())
    return sets_attendus * esperance_jeux_par_set(p_jeu)


def issues_sets(p_set_a: float, best_of: int) -> dict[str, float]:
    """Distribution du SCORE EN SETS, sous indépendance des sets.

    Deuxième hypothèse déclarée, et elle est plus douteuse que la première : un
    joueur qui perd le premier set n'a pas la même probabilité de gagner le
    second qu'avant le match. Le benchmark la sanctionne ou la valide.
    """
    requis = math.ceil(best_of / 2)
    p, q = p_set_a, 1.0 - p_set_a
    issues: dict[str, float] = {}
    for perdus in range(requis):
        n = requis + perdus - 1
        arrangements = math.comb(n, perdus)
        issues[f"{requis}-{perdus}"] = arrangements * p ** requis * q ** perdus
        issues[f"{perdus}-{requis}"] = arrangements * q ** requis * p ** perdus
    return issues


def p_match(p_set_a: float, best_of: int) -> float:
    return sum(v for k, v in issues_sets(p_set_a, best_of).items()
               if int(k.split("-")[0]) > int(k.split("-")[1]))


def total_sets(p_set_a: float, best_of: int) -> dict[str, float]:
    """Nombre de sets JOUÉS. C'est ce que cote le marché « total de sets »."""
    par_total: dict[str, float] = {}
    for score, p in issues_sets(p_set_a, best_of).items():
        n = sum(int(x) for x in score.split("-"))
        par_total[str(n)] = par_total.get(str(n), 0.0) + p
    return par_total
