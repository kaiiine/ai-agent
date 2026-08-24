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
    #: Rendement intéressant, mais probabilité trop basse pour une demande de
    #: sûreté. Le candidat n'est ni supprimé ni relégué au 5e rang du MÊME
    #: classement : il part dans une section distincte, qui dit ce qu'elle est.
    VALEUR_RISQUEE = "VALEUR_RISQUEE"


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
    #: ESTIMATED si un intervalle a réellement été mesuré, NOT_ESTIMATED sinon.
    #: Sans lui, l'absence de `probability_low` était indistinguable d'une donnée
    #: manquante, et rien ne pouvait DIRE à l'utilisateur qu'aucune borne
    #: prudente n'existe encore.
    probability_low_status: str = "NOT_ESTIMATED"
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
    # La probabilité N'ENTRE PAS ici, volontairement. Une première version la
    # multipliait au score avec un poids par profil (0,85 / 0,60 / 0,25) — trois
    # nombres qu'aucun banc de mesure ne justifiait, et qui laissaient un gros
    # EV racheter une probabilité nettement plus faible. La sécurité est traitée
    # par l'ORDRE (`_trier`, posture SURETE), pas par un mélange pondéré.
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

class RecommendationPosture(str, Enum):
    """Ce que l'utilisateur cherche — et donc ce qui décide de l'ordre.

    SAFETY_FIRST est le DÉFAUT : ne rien demander ne doit pas exposer au risque.

    Mélanger sécurité et rendement dans un score unique laisse toujours un gros
    EV racheter une probabilité nettement plus faible — un arbitrage caché
    derrière un poids. Ici l'arbitrage est explicite et porté par la demande.

    Cette posture doit voyager JUSQU'À l'allocation d'argent. Le jour où un
    modèle devient SUPPORTED, un chemin de mise qui repartirait sur « EV
    d'abord » contredirait la demande de l'utilisateur sans le lui dire.
    """
    SAFETY_FIRST = "SAFETY_FIRST"   # la probabilité décide, l'espérance départage
    VALUE_FIRST = "VALUE_FIRST"     # l'espérance décide — seulement si demandé

    # Anciens noms, conservés le temps que les appelants migrent.
    SURETE = "SAFETY_FIRST"
    VALEUR = "VALUE_FIRST"


#: Alias historique.
Posture = RecommendationPosture


#: Largeur de la bande dans laquelle deux probabilités sont tenues pour
#: ÉQUIVALENTES, et où l'espérance reprend la main.
#:
#: C'est une CONVENTION, pas une mesure — et elle est assumée comme telle. La
#: valeur juste serait l'incertitude propre du modèle, mais aucun intervalle
#: réel n'existe tant qu'un modèle est EXPERIMENTAL : `probability_low` y répète
#: l'estimation ponctuelle et se signale `NOT_ESTIMATED`. Cinq points est
#: l'ordre de grandeur d'un écart qu'un modèle non calibré ne peut pas
#: prétendre distinguer.
ESTIMEE = "ESTIMATED"
NON_ESTIMEE = "NOT_ESTIMATED"


def probabilite_de_surete(c: "ReviewCandidate") -> tuple[float | None, str]:
    """La probabilité sur laquelle la SÛRETÉ se juge, et d'où elle vient.

    `probability_low` quand un intervalle a été mesuré ; à défaut la probabilité
    centrale, EXPLICITEMENT signalée comme telle. Aucune valeur n'est fabriquée :
    on ne minore pas artificiellement un point estimé pour se donner l'air
    prudent.

    Tant qu'un modèle est EXPERIMENTAL, aucun intervalle n'existe (`one_x_two.py`
    répète le point et déclare `NOT_ESTIMATED`), et `candidat_depuis_evaluation`
    met donc `probability_low` à None. Trier là-dessus mettrait TOUS les
    candidats à égalité et laisserait l'espérance décider — c'est-à-dire le
    comportement que ce chantier corrige, revenu en silence.
    """
    if c.probability_low is not None and c.probability_low_status == ESTIMEE:
        return c.probability_low, ESTIMEE
    return c.fair_probability, NON_ESTIMEE


#: Écart de probabilité au-delà duquel une sélection n'est plus « du même ordre
#: de sûreté » que la meilleure du scan et part en section VALEUR / RISQUE ÉLEVÉ.
#:
#: CONVENTION D'AFFICHAGE (UX grouping convention), pas une mesure statistique.
#: Elle n'altère aucune probabilité, aucune espérance, aucune maturité et aucune
#: décision de mise : elle ne fait que séparer deux listes à l'écran.
#:
#: Exprimée en points de probabilité, en continu. Une version antérieure
#: découpait en bandes de 5 points ; c'était une falaise — 0,55 et 0,53, distants
#: de deux points, tombaient de part et d'autre d'une frontière. Le tri est
#: désormais continu et la bande a disparu du classement.
ECART_SECTION = Decimal("0.25")

#: Écart, en bandes, au-delà duquel une sélection n'est plus « du même ordre de
#: sûreté » que la meilleure du run et part en section « valeur risquée ».
#:
#: RELATIF, et non un plancher absolu. Un plancher fixe est arbitraire deux fois :
#: il ne sait pas ce qui est offert ce jour-là, et le premier essai (45 %, puis
#: 60 %) l'a montré — 60 % effaçait jusqu'aux candidats à 55 %, pourtant les
#: meilleurs de leur run. L'écart, lui, se lit sur l'offre réelle : cinq bandes
#: = 25 points de probabilité sous la tête, ce qu'aucun modèle ne rattrape par
#: du rendement.
#:
#: Un profil PEUT en plus imposer un plancher absolu (`min_probability`), et le
#: profil conservateur le fait. Les deux règles se cumulent.
ECART_MAX_BANDES = 5


def _cle_surete(r: "RankedCandidate") -> tuple:
    """probabilité de sûreté ▸ qualité ▸ fraîcheur ▸ espérance ▸ identité."""
    proba, _ = probabilite_de_surete(r.candidate)
    return (-(proba or 0.0),
            -(r.candidate.data_quality or 0.0),
            -(r.candidate.freshness or 0.0),
            -(r.expected_value_low or Decimal(0)),
            r.candidate.source_event_id, r.candidate.family.value,
            r.candidate.selection)


def _cle_valeur(r: "RankedCandidate") -> tuple:
    """espérance ▸ qualité ▸ fraîcheur ▸ probabilité (garde) ▸ identité."""
    proba, _ = probabilite_de_surete(r.candidate)
    return (-(r.expected_value_low or Decimal(0)),
            -(r.candidate.data_quality or 0.0),
            -(r.candidate.freshness or 0.0),
            -(proba or 0.0),
            r.candidate.source_event_id, r.candidate.family.value,
            r.candidate.selection)


def _trier(candidats: Sequence["RankedCandidate"],
           posture: "RecommendationPosture" = None) -> list["RankedCandidate"]:
    """Ordre LEXICOGRAPHIQUE, jamais un score pondéré.

    En sûreté, la probabilité décide et l'espérance ne départage qu'à qualité et
    fraîcheur égales : une sélection nettement moins probable ne peut donc PAS
    passer devant une plus sûre en vertu d'un meilleur rendement. C'est ce qu'un
    score pondéré autorisait, l'arbitrage caché derrière un poids.

    En valeur — et seulement si elle est explicitement demandée — l'espérance
    prend la tête, la probabilité restant en garde.
    """
    posture = posture or RecommendationPosture.SAFETY_FIRST
    return sorted(candidats,
                  key=_cle_valeur if posture is RecommendationPosture.VALUE_FIRST else _cle_surete)


def evaluer(candidats: Sequence[ReviewCandidate], *, profil=None,
            posture: RecommendationPosture | None = None) -> list[RankedCandidate]:
    """Chaque candidat -> comparabilité, score prudent, statut produit."""
    # La référence de sûreté du run : la meilleure borne basse offerte. C'est
    # elle qui rend l'écart LISIBLE — « nettement moins sûr que ce qui existe
    # aujourd'hui » plutôt que « sous un nombre décidé d'avance ».
    tete = max((probabilite_de_surete(c)[0] for c in candidats
                if probabilite_de_surete(c)[0] is not None), default=None)
    sortie: list[RankedCandidate] = []
    for c in candidats:
        comparable, motifs = comparabilite(c)
        if comparable is Comparability.NOT_COMPARABLE:
            sortie.append(RankedCandidate(c, comparable, ProductStatus.NOT_COMPARABLE,
                                          reasons=motifs + tuple(c.abstention_reasons)))
            continue
        ev_low = esperance_prudente(c)
        score = score_prudent(c, profil=profil)

        # Plancher de probabilité : sous ce seuil, une sélection n'est pas
        # proposée du tout, quel que soit son rendement. C'est la traduction de
        # « je veux des paris sûrs » : une espérance flatteuse sur un coup à
        # 45 % reste un coup à 45 %.
        # Le sectionnement ne s'applique QU'EN posture de sûreté : si la valeur
        # est explicitement demandée, un pari risqué n'est plus hors sujet.
        motif = (_motif_de_risque(c, tete, profil)
                 if (posture or RecommendationPosture.SAFETY_FIRST) is RecommendationPosture.SAFETY_FIRST else None)
        if motif:
            sortie.append(RankedCandidate(
                c, comparable, ProductStatus.VALEUR_RISQUEE, score, ev_low,
                reasons=(motif,) + tuple(c.abstention_reasons)))
            continue

        statut = (ProductStatus.ACTIONABLE if c.maturity == MATURITE_ACTIONABLE
                  else ProductStatus.REVIEW)
        sortie.append(RankedCandidate(c, comparable, statut, score, ev_low))
    return sortie


def _plancher_probabilite(profil) -> Decimal:
    """Le plancher ABSOLU du profil, ou zéro s'il n'en déclare pas."""
    if profil is None:
        from ...advisor.ranking.profiles import load_ranking_profiles
        profil = load_ranking_profiles()["balanced_v1"]
    return getattr(profil, "min_probability", Decimal(0)) or Decimal(0)


def _motif_de_risque(c: ReviewCandidate, tete: float | None, profil) -> str | None:
    """Pourquoi cette sélection n'est pas « du même ordre de sûreté », ou None.

    Deux règles cumulatives : l'écart à la meilleure du run, et le plancher
    absolu que le profil déclare éventuellement. Un candidat sans borne basse
    n'est pas sectionné — on ne lui reproche pas une mesure qui manque.
    """
    valeur, statut = probabilite_de_surete(c)
    if valeur is None:
        return None
    proba = Decimal(str(valeur))
    if tete is not None:
        ecart = Decimal(str(tete)) - proba
        if ecart > ECART_SECTION:
            precision = ("" if statut == ESTIMEE
                         else " (probabilité centrale, intervalle non estimé)")
            return (f"probabilité {proba:.1%}{precision}, soit {ecart:.0%} sous "
                    f"la meilleure du scan ({Decimal(str(tete)):.1%})")
    plancher = _plancher_probabilite(profil)
    if plancher > 0 and proba < plancher:
        return f"probabilité {proba:.1%} sous le plancher {plancher:.0%} du profil"
    return None


def best_market_per_event(candidats: Sequence[ReviewCandidate], *, profil=None,
                          posture: RecommendationPosture | None = None) -> dict:
    """Pour chaque événement, tous ses marchés évaluables, classés — et le meilleur.

    C'est la vue produit centrale : elle permet de dire « ce match est
    intéressant, mais pas par son vainqueur ».
    """
    par_evenement: dict[str, list[RankedCandidate]] = {}
    evalues = [r for r in evaluer(candidats, profil=profil, posture=posture)
               if r.status is not ProductStatus.VALEUR_RISQUEE]
    for r in meilleure_par_marche(evalues):
        par_evenement.setdefault(r.candidate.source_event_id, []).append(r)

    resultat = {}
    for evenement, lignes in par_evenement.items():
        classees = [
            RankedCandidate(r.candidate, r.comparability, r.status, r.score,
                            r.expected_value_low, r.reasons, event_rank=i + 1)
            for i, r in enumerate(_trier(lignes))]
        resultat[evenement] = classees
    return resultat


def classement_global(candidats: Sequence[ReviewCandidate], *, profil=None,
                      posture: RecommendationPosture | None = None) -> list[RankedCandidate]:
    """Fusionne les meilleurs marchés de tous les événements et de tous les sports."""
    fusion: list[RankedCandidate] = []
    for lignes in best_market_per_event(candidats, profil=profil,
                                       posture=posture).values():
        fusion.extend(lignes)
    return [RankedCandidate(r.candidate, r.comparability, r.status, r.score,
                            r.expected_value_low, r.reasons, r.event_rank, i + 1)
            for i, r in enumerate(_trier(fusion, posture))]
