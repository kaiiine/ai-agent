"""Classement REVUE, tous sports et tous marchés — comparer ce qui est comparable.

L'objectif produit : parmi tous les paris qu'AXON sait réellement évaluer,
faire remonter les meilleurs, quel que soit le sport ou la famille. Ce qui
suppose d'abord de refuser de comparer ce qui ne l'est pas.

CE QUI N'EST PAS FAVORISÉ, ET C'EST VÉRIFIÉ PAR DES TESTS : ni `MATCH_WINNER`,
ni le football, ni les grosses cotes, ni les probabilités élevées. Le score ne
lit ni le nom du sport, ni celui de la famille.

LE SCORE EST PRUDENT, PAS OPTIMISTE. Il repose sur l'espérance calculée à la
BORNE BASSE, pas au point : c'est ce qui sépare « probabilité centrale élevée
mais mal bornée » de « probabilité plus modeste et solidement encadrée ». Les
composants viennent de l'Advisor (`value_component`, `quality_component`,
`freshness_component`) — aucune seconde échelle n'est inventée ici.

CE MODULE NE PROMEUT RIEN. Il consomme la maturité, il ne la produit pas. Un
marché premier du classement REVUE reste EXPERIMENTAL tant que le ledger le dit :
être intéressant n'a jamais rendu personne misable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ..value_engine.settlement import OutcomeShare, Settlement
from ..value_engine.settlement import expected_value as ev_settlement
from .families import MarketFamily


class Comparability(str, Enum):
    COMPARABLE = "COMPARABLE"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class ProductStatus(str, Enum):
    REVIEW = "REVIEW"            # évaluable et comparable, mais pas misable
    ACTIONABLE = "ACTIONABLE"    # maturité SUPPORTED — décidé ailleurs, jamais ici
    NOT_COMPARABLE = "NOT_COMPARABLE"


#: Maturité qui autorise la mise. Reprise du vocabulaire du ledger ; ce module ne
#: fait que la LIRE.
MATURITE_ACTIONABLE = "SUPPORTED"


@dataclass(frozen=True)
class ReviewCandidate:
    """L'objet économique commun vers lequel tout marché évaluable converge."""

    source_event_id: str
    sport: str
    competition: str | None
    family: MarketFamily
    parameters: Mapping
    context: Mapping
    selection: str
    bookmaker_odds: float | None
    implied_probability: float | None
    vig_adjusted_probability: float | None
    fair_probability: float | None
    probability_low: float | None
    expected_value: float | None
    maturity: str | None
    freshness: float | None
    data_quality: float | None
    probability_origin: str | None
    settlement_shares: tuple = ()
    event_label: str | None = None
    market_source_id: str | None = None
    observed_at: datetime | None = None
    abstention_reasons: tuple[str, ...] = ()
    #: Provenance BRUTE du marché chez la source (§9). Ces champs n'entrent dans
    #: aucun calcul et dans aucun tri : ils existent pour qu'un chiffre affiché
    #: puisse être remonté jusqu'à la ligne exacte du bookmaker qui l'a produit.
    #: Le `betType` en particulier est le seul discriminant structuré de portée —
    #: le perdre en route rendrait invérifiable le refus d'un total de mi-temps.
    bet_type: int | None = None
    bet_type_name: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    bookmaker: str | None = None
    #: Identité CANONIQUE de la rencontre et de ses participants. Elles ne
    #: servent à aucun calcul : elles permettent de NOMMER une issue. Sans elles,
    #: une sélection s'affiche « player_a », c'est-à-dire un rôle interne là où
    #: l'utilisateur attend un nom de joueur.
    event_id: str | None = None
    participant_ids: tuple[str, ...] = ()
    #: Coup d'envoi. N'entre dans AUCUN calcul — il sert à DISTINGUER deux
    #: rencontres des mêmes équipes. Une série de baseball en programme deux en
    #: deux jours : sans l'horaire, deux jambes de combiné parfaitement
    #: distinctes s'affichent à l'identique, et la liste paraît boguée là où elle
    #: est juste. L'horaire est LU sur l'évaluation, jamais dérivé de
    #: `event_id` — un identifiant n'est pas une source de faits.
    scheduled_at: datetime | None = None

    @property
    def edge(self) -> float | None:
        """L'écart entre ce que le modèle croit et ce que le marché fait payer.

        Mesuré contre `vig_adjusted_probability` quand elle existe — c'est le prix
        du bookmaker DÉBARRASSÉ de sa marge, donc le seul contre lequel un écart
        signifie quelque chose. Comparer à `implied_probability` compterait la
        marge comme de l'avantage, et rendrait un edge positif sur un marché où le
        modèle est en réalité d'accord avec le bookmaker.

        `None` quand l'une des deux grandeurs manque : une absence ne se remplace
        pas par l'autre référence, sinon deux candidats afficheraient sous le même
        intitulé deux quantités différentes.
        """
        reference = (self.vig_adjusted_probability
                     if self.vig_adjusted_probability is not None
                     else None)
        if reference is None or self.fair_probability is None:
            return None
        return self.fair_probability - reference

    @property
    def edge_prudent(self) -> float | None:
        """Le même écart, pris depuis la BORNE BASSE de la probabilité.

        C'est celui qui survit à l'incertitude du modèle. Il est plus petit que
        `edge` par construction, et peut être négatif là où `edge` est positif —
        auquel cas l'avantage n'est pas démontré, seulement estimé.
        """
        if self.vig_adjusted_probability is None or self.probability_low is None:
            return None
        return self.probability_low - self.vig_adjusted_probability

    @property
    def market_key(self) -> tuple:
        """Le MARCHÉ, sans sa sélection : deux côtés d'un même Plus/Moins la
        partagent, et ne sont donc pas deux opportunités."""
        return (self.source_event_id, self.family.value,
                tuple(sorted((k, str(v)) for k, v in (self.parameters or {}).items()
                             if k != "source_family_id")))


@dataclass(frozen=True)
class RankedCandidate:
    candidate: ReviewCandidate
    comparability: Comparability
    status: ProductStatus
    score: Decimal | None = None
    expected_value_low: float | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    event_rank: int | None = None
    global_rank: int | None = None


# ── Comparabilité : ce qui manque n'est jamais remplacé ──────────────────────

#: Grandeurs sans lesquelles un candidat ne se compare pas. Chacune est REFUSÉE
#: à l'absence plutôt que remplacée : un `None` devenu `0` classerait le candidat
#: en dernier au lieu de le sortir du classement — deux choses très différentes,
#: dont une seule est honnête.
_INDISPENSABLES = (
    ("fair_probability", "probabilité de modèle absente"),
    ("probability_low", "probability_low NOT_ESTIMATED — l'incertitude n'est pas mesurée"),
    ("bookmaker_odds", "aucune cote observée"),
    ("freshness", "fraîcheur non mesurable"),
    ("data_quality", "qualité de données non mesurée"),
    ("maturity", "maturité inconnue"),
)


def _seuil_qualite() -> float:
    """Le seuil de qualité de données du moteur — LU, jamais choisi ici.

    C'est celui de `bet_decision_policy`, la politique versionnée qui décide déjà
    si une prédiction mérite qu'on agisse dessus. Elle n'est appliquée
    aujourd'hui que sur le chemin SUPPORTED : un modèle EXPERIMENTAL ne la
    rencontre jamais, et ses prédictions entraient donc dans le classement sans
    qu'aucune porte ne les ait vues.
    """
    from ..value_engine.bet_policy import default_bet_decision_policy
    return float(default_bet_decision_policy().min_data_quality)


def comparabilite(candidat: ReviewCandidate) -> tuple[Comparability, tuple[str, ...]]:
    """Ce candidat peut-il être MIS EN FACE d'un autre ?

    Le refus le moins évident est celui de la QUALITÉ DES DONNÉES, et c'est le
    plus important. Mesuré sur un run réel de mi-août : le modèle football
    déclarait `form_insufficient` pour les deux équipes de chaque rencontre
    portugaise — une et deux journées jouées — et tirait donc ses forces vers la
    moyenne de la ligue. Ses probabilités ne décrivaient plus les équipes, mais
    le championnat : 0,55 de victoire pour Rio Ave contre le FC Porto, coté 6,25.
    Le classement en faisait un « +86 % d'espérance » et le plaçait en tête.

    Ce n'est pas un edge, c'est un écart d'information — dans le mauvais sens. Et
    la borne basse ne le rattrape pas : elle est mesurée en fonction de la
    probabilité prédite, pas du volume de données derrière elle (cf. la limite
    déclarée de `uncertainty.py`). Une prédiction de saison pleine et une
    prédiction de deuxième journée reçoivent la même borne.

    Le seuil appliqué n'est pas inventé ici : c'est celui du moteur.
    """
    manquants = [motif for champ, motif in _INDISPENSABLES
                 if getattr(candidat, champ, None) is None]
    if manquants:
        return Comparability.NOT_COMPARABLE, tuple(manquants)
    if candidat.bookmaker_odds is not None and candidat.bookmaker_odds <= 1.0:
        return Comparability.NOT_COMPARABLE, ("cote invalide (<= 1)",)
    seuil = _seuil_qualite()
    if candidat.data_quality < seuil:
        return Comparability.NOT_COMPARABLE, (
            f"DATA_QUALITY_INSUFFICIENT — qualité mesurée {candidat.data_quality:.3f} "
            f"< {seuil:.2f} (seuil du moteur) : le modèle déclare lui-même n'avoir "
            "eu qu'une partie de ses entrées pour cette rencontre",)
    return Comparability.COMPARABLE, ()


# ── Espérance prudente ───────────────────────────────────────────────────────

def esperance_prudente(candidat: ReviewCandidate) -> float | None:
    """L'espérance calculée à la BORNE BASSE, via la primitive settlement-aware.

    La masse retirée à l'issue gagnante rejoint la PERTE, jamais le remboursement :
    on ne rend pas un pari plus sûr en le bornant. Sur un marché à push, la part
    remboursée est une propriété du marché et ne bouge pas.
    """
    if candidat.probability_low is None or not candidat.bookmaker_odds:
        return None
    basse = candidat.probability_low

    if not candidat.settlement_shares:
        parts = (OutcomeShare(basse, Settlement.WIN),
                 OutcomeShare(1.0 - basse, Settlement.LOSS))
        return ev_settlement(parts, candidat.bookmaker_odds)

    push = sum(p.probability for p in candidat.settlement_shares
               if p.settlement in (Settlement.PUSH, Settlement.VOID))
    gagnante = min(basse * (1.0 - push), 1.0 - push)
    parts = (OutcomeShare(gagnante, Settlement.WIN),
             OutcomeShare(push, Settlement.PUSH),
             OutcomeShare(max(0.0, 1.0 - push - gagnante), Settlement.LOSS))
    return ev_settlement(parts, candidat.bookmaker_odds)


def _fiabilite(maturite: str | None, profil) -> Decimal:
    """Escompte de fiabilité par maturité, ANCRÉ sur la baseline de l'Advisor.

    La valeur de référence n'est pas choisie ici : c'est `supported_baseline` du
    profil de classement, celle qu'utilise déjà `reliability_component`. Un
    EXPERIMENTAL en reçoit une fraction STRICTEMENT inférieure, et un statut
    inconnu moins encore. L'ordre est ce qui compte — le classement de revue
    ordonne des candidats entre eux, il ne les rapproche jamais de la mise.
    """
    base = Decimal(str(profil.supported_baseline))
    if maturite == MATURITE_ACTIONABLE:
        return base
    if maturite:
        return base / 2
    return base / 4


def score_prudent(candidat: ReviewCandidate, *, profil=None) -> Decimal | None:
    """Score de revue — composants de l'Advisor, aucune échelle nouvelle."""
    from ...advisor.ranking.components import (
        freshness_component, quality_component, value_component,
    )
    from ...advisor.ranking.profiles import load_ranking_profiles

    ev_low = esperance_prudente(candidat)
    if ev_low is None:
        return None
    profil = profil or load_ranking_profiles()["balanced_v1"]

    valeur = value_component(Decimal(str(round(ev_low, 6))), profil)
    qualite = quality_component(Decimal(str(candidat.data_quality)))
    fraicheur = freshness_component(Decimal(str(candidat.freshness)), profil)
    fiabilite = _fiabilite(candidat.maturity, profil)
    return (valeur * fiabilite * (qualite + fraicheur) / 2).quantize(Decimal("0.000001"))


# ── Une seule sélection économique par marché ────────────────────────────────

def meilleure_par_marche(classes: Sequence[RankedCandidate]) -> list[RankedCandidate]:
    """Deux côtés d'un même marché ne sont pas deux opportunités.

    « Plus de 2,5 » et « Moins de 2,5 » décrivent la même opinion vue des deux
    bords : au plus l'un des deux peut avoir une espérance favorable, et les
    afficher tous les deux gonflerait la liste sans rien ajouter. Les données des
    deux côtés restent dans l'audit — c'est la LISTE qui se restreint.
    """
    meilleurs: dict[tuple, RankedCandidate] = {}
    for r in classes:
        if r.comparability is not Comparability.COMPARABLE:
            continue
        cle = r.candidate.market_key
        garde = meilleurs.get(cle)
        if garde is None or (r.score or Decimal(0)) > (garde.score or Decimal(0)):
            meilleurs[cle] = r
    return list(meilleurs.values())


# ── Classements ──────────────────────────────────────────────────────────────

def _trier(candidats: Sequence[RankedCandidate]) -> list[RankedCandidate]:
    """Tri par score décroissant. Départage STABLE et neutre : l'identifiant du
    marché, jamais le sport ni la famille."""
    return sorted(candidats,
                  key=lambda r: (-(r.score or Decimal(0)),
                                 r.candidate.source_event_id,
                                 r.candidate.family.value, r.candidate.selection))


def evaluer(candidats: Sequence[ReviewCandidate], *, profil=None) -> list[RankedCandidate]:
    """Chaque candidat -> comparabilité, score prudent, statut produit."""
    sortie: list[RankedCandidate] = []
    for c in candidats:
        comparable, motifs = comparabilite(c)
        if comparable is Comparability.NOT_COMPARABLE:
            sortie.append(RankedCandidate(c, comparable, ProductStatus.NOT_COMPARABLE,
                                          reasons=motifs + tuple(c.abstention_reasons)))
            continue
        ev_low = esperance_prudente(c)
        score = score_prudent(c, profil=profil)
        statut = (ProductStatus.ACTIONABLE if c.maturity == MATURITE_ACTIONABLE
                  else ProductStatus.REVIEW)
        sortie.append(RankedCandidate(c, comparable, statut, score, ev_low))
    return sortie


def best_market_per_event(candidats: Sequence[ReviewCandidate], *, profil=None) -> dict:
    """Pour chaque événement, tous ses marchés évaluables, classés — et le meilleur.

    C'est la vue produit centrale : elle permet de dire « ce match est
    intéressant, mais pas par son vainqueur ».
    """
    par_evenement: dict[str, list[RankedCandidate]] = {}
    for r in meilleure_par_marche(evaluer(candidats, profil=profil)):
        par_evenement.setdefault(r.candidate.source_event_id, []).append(r)

    resultat = {}
    for evenement, lignes in par_evenement.items():
        classees = [
            RankedCandidate(r.candidate, r.comparability, r.status, r.score,
                            r.expected_value_low, r.reasons, event_rank=i + 1)
            for i, r in enumerate(_trier(lignes))]
        resultat[evenement] = classees
    return resultat


def classement_global(candidats: Sequence[ReviewCandidate], *, profil=None) -> list[RankedCandidate]:
    """Fusionne les meilleurs marchés de tous les événements et de tous les sports."""
    fusion: list[RankedCandidate] = []
    for lignes in best_market_per_event(candidats, profil=profil).values():
        fusion.extend(lignes)
    return [RankedCandidate(r.candidate, r.comparability, r.status, r.score,
                            r.expected_value_low, r.reasons, r.event_rank, i + 1)
            for i, r in enumerate(_trier(fusion))]
