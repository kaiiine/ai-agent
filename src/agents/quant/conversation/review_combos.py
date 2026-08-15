"""Combinés EXPLORATOIRES, construits sur des candidats de REVUE déjà évalués.

Le produit ne montrait aucun combiné dès qu'aucun pari n'était misable : le
constructeur de combinés vit dans le chemin argent, et ce chemin s'arrête avant
lui quand rien n'est éligible. L'utilisateur qui demande « fais-moi un combiné »
recevait donc un refus sec, alors que le moteur avait produit des centaines de
probabilités parfaitement lisibles.

Ce module répond à cette demande SANS ouvrir de porte vers l'argent :

- il ne part QUE de candidats de revue réellement évalués — jamais d'une cote
  brute, jamais d'un marché non canonicalisé ;
- il réutilise `combos.dependency.classify`, la règle de corrélation du chemin
  argent, au lieu d'en réécrire une seconde. Deux règles finiraient par diverger,
  et c'est la plus permissive qui servirait ;
- il ne multiplie JAMAIS deux probabilités sans que l'indépendance ait été
  établie par cette règle. À défaut, la probabilité jointe vaut `NOT_ESTIMATED`
  et l'EV avec elle — un combiné dont on ignore la probabilité n'a pas d'EV, il
  n'a pas une EV de zéro ;
- le statut est EXPERIMENTAL, sans exception et sans chemin de promotion. Aucune
  fonction de ce module ne rend un objet que le dimensionnement sait lire.

La cote combinée, elle, est toujours calculable : c'est le produit des cotes du
bookmaker, une donnée observée et non une estimation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Any, Sequence

from ..advisor.combos.dependency import classify
from ..advisor.domain.enums import DependencyStatus

#: Le seul statut de dépendance qui autorise un produit de probabilités. Repris
#: du chemin argent — ce module ne décide pas de ce qui est indépendant.
_INDEPENDANCE_SUFFISANTE = DependencyStatus.INDEPENDENT_ENOUGH

NOT_ESTIMATED = "NOT_ESTIMATED"


class _LegAdapte:
    """Vue d'un candidat de revue au contrat attendu par `classify`.

    `classify` lit `event_id`, `market_id`, `selection` et `participant_ids`. Un
    `ReviewCandidate` porte les quatre, au nom de `market_key` près. L'adaptateur
    existe pour réutiliser la règle telle quelle plutôt que d'en recopier une
    variante — c'est la copie qui finirait par autoriser ce que l'original refuse.
    """

    __slots__ = ("event_id", "market_id", "selection", "participant_ids")

    def __init__(self, candidat: Any):
        self.event_id = candidat.event_id
        self.market_id = candidat.market_key
        self.selection = candidat.selection
        self.participant_ids = tuple(candidat.participant_ids or ())


@dataclass(frozen=True)
class ComboExploratoire:
    """Un combiné à examiner. Rien ici ne se mise."""

    legs: tuple[Any, ...]
    #: Produit des cotes observées. Toujours calculable.
    cote_combinee: Decimal
    #: Statut de dépendance le PLUS contraignant rencontré entre deux legs.
    #: Peut valoir la chaîne `CORRELATED_SAME_ORIGIN`, qui n'appartient pas à
    #: l'énumération du chemin argent : celle-ci compare des identités, pas des
    #: lois. Deux marchés tirés de la même matrice de score sont corrélés sans
    #: qu'aucune identité ne le trahisse.
    dependance: Any
    #: `None` quand l'indépendance n'est pas établie ou qu'un leg n'a pas de
    #: probabilité mesurée. `None` veut dire NOT_ESTIMATED, jamais zéro.
    probabilite_jointe: Decimal | None = None
    probabilite_jointe_basse: Decimal | None = None
    expected_value: Decimal | None = None
    statut: str = "EXPERIMENTAL"

    @property
    def probabilite_lisible(self) -> str:
        return (NOT_ESTIMATED if self.probabilite_jointe is None
                else f"{self.probabilite_jointe * 100:.2f} %")

    @property
    def ev_lisible(self) -> str:
        if self.expected_value is None:
            return NOT_ESTIMATED
        return f"{'+' if self.expected_value >= 0 else ''}{self.expected_value * 100:.2f} %"

    @property
    def motif_non_estimee(self) -> str | None:
        """Pourquoi la probabilité jointe n'a pas pu être établie."""
        if self.probabilite_jointe is not None:
            return None
        if self.dependance is not _INDEPENDANCE_SUFFISANTE:
            return (f"dépendance {self.dependance_lisible} — multiplier ces "
                    "probabilités supposerait une indépendance que rien n'établit")
        return "une des sélections n'a pas de probabilité mesurée"

    @property
    def dependance_lisible(self) -> str:
        return getattr(self.dependance, "value", str(self.dependance))


def _decimal(valeur: Any) -> Decimal | None:
    if valeur is None:
        return None
    try:
        return Decimal(str(valeur))
    except (ArithmeticError, ValueError):
        return None


#: Deux probabilités issues de la MÊME loi jointe ne sont pas indépendantes,
#: quand bien même leurs événements diffèrent. `probability_origin` porte cette
#: origine (« dixon_coles:score_matrix:event:… ») : l'égalité des deux chaînes
#: signe une corrélation que la classification structurelle, qui ne regarde que
#: les identités, ne peut pas voir.
CORRELATED_SAME_ORIGIN = "CORRELATED_SAME_ORIGIN"


def _dependance_la_plus_contraignante(candidats: Sequence[Any]) -> DependencyStatus:
    """L'ordre contractuel du chemin argent, appliqué à toutes les paires."""
    ordre = (DependencyStatus.INCOMPATIBLE,
             DependencyStatus.STRUCTURALLY_DEPENDENT,
             DependencyStatus.STATISTICALLY_DEPENDENT,
             DependencyStatus.UNKNOWN,
             DependencyStatus.INDEPENDENT_ENOUGH)
    pire = DependencyStatus.INDEPENDENT_ENOUGH
    for a, b in combinations(candidats, 2):
        statut = classify(_LegAdapte(a), _LegAdapte(b))
        if ordre.index(statut) < ordre.index(pire):
            pire = statut
    return pire


def _meme_origine(candidats: Sequence[Any]) -> bool:
    """Deux jambes tirées de la même loi jointe. Jamais multipliables."""
    origines = [getattr(c, "probability_origin", None) for c in candidats]
    connues = [o for o in origines if o]
    return len(connues) > 1 and len(set(connues)) < len(connues)


def _admissible(candidat: Any) -> bool:
    """Les filtres de sécurité, appliqués AVANT toute recherche de proximité.

    Le NIVEAU de qualité et de fraîcheur n'est pas décidé ici : ces candidats
    sortent déjà de la politique d'éligibilité du chemin argent, qui les a jugés
    contre son seuil versionné. Ce qui est exigé ici, c'est que les grandeurs
    soient MESURÉES — une qualité inconnue ne vaut pas une qualité suffisante.
    """
    return (candidat.probability_low is not None
            and candidat.data_quality is not None
            and candidat.freshness is not None
            and candidat.bookmaker_odds is not None)


#: Plafond du vivier exploré. Le nombre de paires croît en n², et l'utilisateur
#: n'a besoin que des plus proches de sa cible : au-delà, on paie du temps pour
#: des combinaisons qui ne remonteront jamais.
_VIVIER_MAX = 60


def construire(rangs: Sequence[Any], *, n_legs: int = 2, top: int = 3,
               objectif: Any = None,
               marge_securite: Decimal = Decimal("1")) -> tuple[ComboExploratoire, ...]:
    """Combinés exploratoires sur les meilleurs candidats de revue.

    `rangs` est le classement DÉJÀ produit par le moteur structuré : ce module
    n'en réordonne aucun et n'en sélectionne aucun sur un critère qui lui serait
    propre. Il prend les premiers, dans l'ordre reçu.

    `marge_securite` reste à 1 par défaut : appliquer ici la marge du chemin
    argent laisserait croire qu'elle a été calibrée pour cet usage, ce qui n'est
    pas le cas. Un combiné exploratoire ne se dimensionne pas.
    """
    candidats = [getattr(r, "candidate", r) for r in rangs]

    # ── 1. Filtres de SÉCURITÉ, d'abord et sans exception ────────────────────
    # L'ordre compte : chercher la proximité à la cote avant de filtrer
    # reviendrait à choisir une jambe pour son prix, puis à vérifier si on a le
    # droit — c'est-à-dire à laisser l'objectif de cote piloter la sélection.
    admissibles = [c for c in candidats if _admissible(c)]

    # Une seule sélection par ÉVÉNEMENT : deux marchés du même match sont
    # structurellement dépendants, les proposer ensemble ne produirait que des
    # combinés NOT_ESTIMATED.
    vus: set = set()
    distincts = []
    for c in admissibles:
        if c.event_id in vus:
            continue
        vus.add(c.event_id)
        distincts.append(c)

    # ── 2. Seulement ensuite, la recherche autour de la cible ────────────────
    # Sans cible, on garde l'ordre reçu et on s'arrête tôt. Avec une cible, on
    # explore un vivier plus large PUIS on trie par proximité — jamais l'inverse.
    vivier = distincts if objectif is not None else distincts[: max(n_legs * top, n_legs)]
    vivier = vivier[:_VIVIER_MAX]

    sorties: list[ComboExploratoire] = []
    for groupe in combinations(vivier, n_legs):
        cotes = [_decimal(c.bookmaker_odds) for c in groupe]
        if any(cote is None for cote in cotes):
            continue
        cote_combinee = Decimal(1)
        for cote in cotes:
            cote_combinee *= cote

        dependance = _dependance_la_plus_contraignante(groupe)
        if dependance is DependencyStatus.INCOMPATIBLE:
            continue
        # Une origine commune l'emporte sur le verdict structurel : deux marchés
        # tirés de la même loi jointe sont corrélés même si leurs identités
        # diffèrent, et la classification par identités ne peut pas le voir.
        if _meme_origine(groupe):
            dependance = CORRELATED_SAME_ORIGIN

        jointe = jointe_basse = ev = None
        if dependance is _INDEPENDANCE_SUFFISANTE:
            moyennes = [_decimal(c.fair_probability) for c in groupe]
            basses = [_decimal(c.probability_low) for c in groupe]
            if all(p is not None for p in moyennes):
                jointe = Decimal(1)
                for p in moyennes:
                    jointe *= p
                jointe *= marge_securite
                ev = jointe * cote_combinee - Decimal(1)
            if all(p is not None for p in basses):
                jointe_basse = Decimal(1)
                for p in basses:
                    jointe_basse *= p
                jointe_basse *= marge_securite

        sorties.append(ComboExploratoire(
            legs=tuple(groupe), cote_combinee=cote_combinee, dependance=dependance,
            probabilite_jointe=jointe, probabilite_jointe_basse=jointe_basse,
            expected_value=ev))
        if objectif is None and len(sorties) >= top:
            break

    if objectif is not None:
        # §7 : minimiser |cote combinée − cible|, une fois seulement que tout ce
        # qui précède a été respecté. Départage TOTAL pour un ordre reproductible.
        sorties.sort(key=lambda c: (abs(c.cote_combinee - objectif.target_odds),
                                    tuple(str(l.event_id) for l in c.legs)))
    return tuple(sorties[:top])
