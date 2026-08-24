"""Le classement produit : tous les sports, toutes les familles, un seul barème.

L'ancienne shortlist ne classait que le marché « qui gagne », parce que c'était le
seul évalué. Maintenant que le Plus/Moins, la double chance, le remboursé-si-nul
et le score exact traversent la même frontière, la question devient : lequel de
ces paris est le meilleur — et la seule réponse honnête commence par refuser de
comparer ce qui n'est pas comparable.

UNE SEULE SOURCE. Les candidats sont construits depuis l'`AdaptedBatch`, c'est-à-
dire depuis la frontière unique du moteur, jamais depuis un second chemin qui
recalculerait les mêmes grandeurs. Un « qui gagne » de tennis et un « plus de 2,5
buts » de football y arrivent par la même route, avec les mêmes champs remplis
par le même adaptateur.

DEUX CHOSES NE SONT JAMAIS FABRIQUÉES ICI :

- une borne basse. `NOT_ESTIMATED` veut dire que l'incertitude n'est pas mesurée,
  et la probabilité centrale n'en tient pas lieu. Le candidat devient
  `NOT_COMPARABLE` avec ce motif, et reste visible ;
- une fraîcheur. Elle est MESURÉE depuis l'instant d'observation des cotes, et
  avec la MÊME règle pour tout le monde — comparer des candidats dont l'un est
  noté sur la fraîcheur de la donnée sportive et l'autre sur celle de la cote
  reviendrait à les classer sur deux échelles différentes.

CE MODULE NE PROMEUT RIEN ET NE MISE RIEN. Il ordonne des candidats de REVUE.
Être premier n'a jamais rendu un modèle misable ; la maturité vient du ledger, et
la mise, du portefeuille.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from ..betting_engine.markets.families import MarketFamily
from ..betting_engine.markets.freshness import evaluer as mesurer_fraicheur
from ..betting_engine.markets.review_ranking import (
    Comparability,
    ProductStatus,
    RankedCandidate,
    ReviewCandidate,
    best_market_per_event,
    classement_global,
)
from ..betting_engine.value_engine.settlement import OutcomeShare, Settlement


def _famille(nom: str | None) -> MarketFamily:
    """Nom de famille -> famille canonique. Une famille inconnue reste `UNMAPPED`
    plutôt que d'être rangée dans la plus proche : classer un marché sous une
    famille qui n'est pas la sienne lui donnerait les règles d'un autre."""
    try:
        return MarketFamily(nom)
    except (ValueError, TypeError):
        return MarketFamily.UNMAPPED


def _parts(shares) -> tuple:
    reconstruites = []
    for issue, probabilite in shares or ():
        try:
            reconstruites.append(OutcomeShare(float(probabilite), Settlement(issue)))
        except (ValueError, TypeError):
            return ()          # une partition à moitié lisible n'en est pas une
    return tuple(reconstruites)


def candidat_depuis_evaluation(evaluation: Any, *, freshness_at: datetime) -> ReviewCandidate:
    """Une évaluation adaptée -> un candidat comparable.

    `probability_low` n'est repris QUE s'il est déclaré ESTIMÉ. Six modèles sur
    sept mesurent leur borne ; celui qui ne la mesure pas répète sa probabilité
    centrale avec le statut `NOT_ESTIMATED`, et reprendre ce nombre le ferait
    passer pour un minorant.

    `freshness_at` est l'instant auquel l'âge des cotes est mesuré — la fin de
    l'acquisition, pas le point-in-time du modèle. Ce dernier est capturé AVANT
    le scan (garantie de non-fuite), si bien que toute cote lui est postérieure
    et que son âge y serait négatif.
    """
    provenance = evaluation.provenance
    estimee = evaluation.uncertainty_status == "ESTIMATED"
    fraicheur = mesurer_fraicheur(evaluation.observed_at, freshness_at)
    return ReviewCandidate(
        source_event_id=(provenance.source_event_id if provenance else None)
                        or evaluation.event_id,
        sport=evaluation.sport,
        competition=evaluation.competition_id,
        family=_famille(provenance.market_family if provenance else evaluation.market_type),
        parameters=dict(provenance.parameters) if provenance else {},
        context={},
        selection=evaluation.selection,
        bookmaker_odds=float(evaluation.bookmaker_odds),
        implied_probability=(float(evaluation.implied_probability_raw)
                             if evaluation.implied_probability_raw is not None else None),
        vig_adjusted_probability=(float(evaluation.no_vig_probability)
                                  if evaluation.no_vig_probability is not None else None),
        fair_probability=float(evaluation.fair_probability),
        probability_low=float(evaluation.probability_low) if estimee else None,
        probability_low_status="ESTIMATED" if estimee else "NOT_ESTIMATED",
        expected_value=(float(evaluation.expected_value)
                        if evaluation.expected_value is not None else None),
        maturity=evaluation.model_maturity,
        freshness=fraicheur.score,
        data_quality=float(evaluation.data_quality),
        probability_origin=provenance.probability_origin if provenance else None,
        settlement_shares=_parts(provenance.settlement_shares if provenance else ()),
        event_label=provenance.event_label if provenance else None,
        market_source_id=provenance.bookmaker_market_id if provenance else None,
        observed_at=evaluation.observed_at,
        abstention_reasons=(() if estimee else
                            ("probability_low NOT_ESTIMATED — l'incertitude de ce "
                             "modèle n'est pas mesurée",)),
        bet_type=provenance.raw_bet_type if provenance else None,
        bet_type_name=provenance.raw_bet_type_name if provenance else None,
        model_name=provenance.model_name if provenance else None,
        model_version=evaluation.model_version,
        bookmaker=evaluation.bookmaker,
        event_id=evaluation.event_id,
        participant_ids=tuple(evaluation.participant_ids),
        scheduled_at=getattr(evaluation, "scheduled_at", None),
    )


@dataclass(frozen=True)
class MarketReview:
    """La vue produit multi-marché d'un run : le global, et le détail par match."""

    global_ranking: tuple[RankedCandidate, ...] = ()
    par_evenement: dict = field(default_factory=dict)
    #: Candidats écartés du classement faute d'une grandeur, avec leur motif.
    #: Ils ne disparaissent pas : « pas comparable » est une réponse.
    non_comparables: tuple[RankedCandidate, ...] = ()
    #: Candidats REFUSÉS par la politique d'éligibilité, avec ses raisons.
    #: `(clé de marché, raisons)`. Ils n'entrent dans aucun classement — mais les
    #: compter est ce qui distingue « aucune opportunité » de « des opportunités
    #: dont la politique n'a pas voulu ».
    ecartes_par_politique: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: TOUS les candidats comparables, AVANT la réduction à un côté par marché.
    #:
    #: `global_ranking` ne garde qu'un côté de chaque marché — celui au meilleur
    #: score, c'est-à-dire orienté espérance. C'est le bon choix pour classer des
    #: opportunités, et le mauvais dès que l'utilisateur demande une PROBABILITÉ :
    #: sur « Moins de 5,5 buts » à 1.11, le côté conservé était le « Plus » à
    #: grosse cote, et le côté à 91 % de borne basse — précisément celui demandé —
    #: disparaissait de l'affichage. Mesuré sur un run réel : trois candidats à
    #: 91 % existaient, un seul était montrable.
    #:
    #: Ce champ ne sert QU'À L'AFFICHAGE d'une préférence utilisateur. Aucune
    #: décision d'argent ne le lit, et le classement reste inchangé.
    comparables: tuple[RankedCandidate, ...] = ()

    @property
    def review(self) -> tuple[RankedCandidate, ...]:
        """Les comparables NON misables. Aucune mise ne sort d'ici."""
        return tuple(r for r in self.global_ranking if r.status is ProductStatus.REVIEW)

    @property
    def review_tous_cotes(self) -> tuple[RankedCandidate, ...]:
        """Les REVIEW comparables, LES DEUX CÔTÉS de chaque marché conservés.

        À n'utiliser que pour répondre à une préférence de probabilité. Retomber
        sur `review` quand le champ est vide garde les appelants anciens corrects.
        """
        source = self.comparables or self.global_ranking
        return tuple(r for r in source if r.status is ProductStatus.REVIEW)

    @property
    def actionable(self) -> tuple[RankedCandidate, ...]:
        """Maturité SUPPORTED. La décision d'argent reste au portefeuille : cette
        liste dit « rien ne l'interdit côté modèle », pas « mise dessus »."""
        return tuple(r for r in self.global_ranking if r.status is ProductStatus.ACTIONABLE)

    def meilleur_de(self, event_id: str) -> RankedCandidate | None:
        lignes = self.par_evenement.get(event_id) or ()
        return lignes[0] if lignes else None

    @property
    def evenements_dont_le_meilleur_n_est_pas_le_vainqueur(self) -> tuple[str, ...]:
        """Les rencontres où le meilleur marché n'est PAS « qui gagne ».

        C'est la mesure produit du chantier : si elle vaut zéro sur tous les runs,
        évaluer cinq familles n'aura rien changé à ce qu'on montre.
        """
        return tuple(
            event_id for event_id, lignes in self.par_evenement.items()
            if lignes and lignes[0].candidate.family is not MarketFamily.MATCH_WINNER)


def construire_review(batch: Any, *, freshness_at: datetime,
                      policy_evaluations: Sequence[Any] = (),
                      profil=None, posture=None) -> MarketReview:
    """`AdaptedBatch` + verdicts de politique -> classement produit.

    LA POLITIQUE D'ÉLIGIBILITÉ EST LA MÊME QUE CELLE DU CHEMIN ARGENT, et ce
    n'est pas un détail d'implémentation. Un classement construit directement sur
    le batch adapté REFAIT une porte d'entrée à côté de celle qui existe : il a
    remonté en tête, sur un run réel, un « Rio Ave bat le FC Porto » à +24 %
    d'edge que la politique venait précisément d'écarter en `LOW_DATA_QUALITY`.
    Le modèle y annonçait `form_insufficient` pour les deux équipes — ses forces
    étaient tirées vers la moyenne de la ligue, donc sa probabilité ne disait
    rien des équipes, seulement du prior. C'est exactement « voir une cote,
    inventer une probabilité, recommander », par la porte de service.

    Les candidats refusés ne DISPARAISSENT pas : ils sortent du classement et
    sont comptés avec les raisons de la politique. Un seuil n'est ni inventé ni
    déplacé ici — celui qui s'applique est celui, versionné, du profil de risque
    de la demande.
    """
    refus = {}
    admis = set()
    for evaluation in policy_evaluations or ():
        candidat = evaluation.candidate
        cle = (candidat.event_id, candidat.market_type, candidat.selection)
        if getattr(evaluation.status, "value", evaluation.status) == "REJECTED":
            refus[cle] = tuple(evaluation.policy_reasons)
        else:
            admis.add(cle)

    candidats, ecartes = [], []
    for evaluation in batch.evaluations:
        cle = (evaluation.event_id, evaluation.market_type, evaluation.selection)
        if cle in refus:
            ecartes.append((f"{evaluation.market_type}/{evaluation.selection}", refus[cle]))
            continue
        # Sans verdict de politique du tout (aucune évaluation fournie), on classe
        # ce qu'on a : c'est le mode d'un appelant qui n'a pas de pipeline sous la
        # main. Avec des verdicts, un candidat absent des ADMIS n'a pas été jugé
        # et n'entre pas — mieux vaut ne pas classer que classer sans jugement.
        if policy_evaluations and cle not in admis:
            ecartes.append((f"{evaluation.market_type}/{evaluation.selection}",
                            ("NOT_EVALUATED_BY_POLICY",)))
            continue
        candidats.append(candidat_depuis_evaluation(evaluation, freshness_at=freshness_at))

    return construire_review_depuis(candidats, profil=profil, posture=posture,
                                    ecartes_par_politique=tuple(ecartes))


def construire_review_depuis(candidats: Sequence[ReviewCandidate], *, profil=None,
                             posture=None,
                             ecartes_par_politique: tuple = ()) -> MarketReview:
    classement = classement_global(candidats, profil=profil, posture=posture)
    par_evenement = best_market_per_event(candidats, profil=profil, posture=posture)
    from ..betting_engine.markets.review_ranking import evaluer as evaluer_candidats
    evalues = evaluer_candidats(candidats, profil=profil)
    non_comparables = tuple(
        r for r in evalues if r.comparability is Comparability.NOT_COMPARABLE)
    comparables = tuple(
        r for r in evalues if r.comparability is Comparability.COMPARABLE)
    return MarketReview(tuple(classement), par_evenement, non_comparables,
                        ecartes_par_politique, comparables)
