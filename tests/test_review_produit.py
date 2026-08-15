"""Le classement produit : ce qui entre, ce qui n'entre pas, et pourquoi.

Le risque de cette couche n'est pas de mal classer — c'est de classer du tout ce
qui n'aurait pas dû être proposé. Un classement construit à côté de la politique
d'éligibilité en refait une porte d'entrée, et un candidat écarté du chemin
argent y remonte en tête de liste sans que rien ne le signale.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.agents.quant.advisor.domain.enums import CandidateStatus
from src.agents.quant.advisor.input_adapter.schema import (
    AdaptedBatch,
    AdaptedEvaluation,
    AdaptedExplanation,
    MarketProvenance,
)
from src.agents.quant.betting_engine.markets.review_ranking import (
    Comparability,
    ProductStatus,
)
from src.agents.quant.conversation.market_review import (
    candidat_depuis_evaluation,
    construire_review,
)

_T = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
_OBSERVE = _T - timedelta(seconds=20)


def _evaluation(*, event="event:football:nld:1:home=a|away=b", market="TOTALS(line=2.5)",
                selection="over", odds="1.80", fair="0.58", low="0.53",
                incertitude="ESTIMATED", maturity="EXPERIMENTAL", qualite="1.0",
                famille="TOTALS", parametres=(("line", "2.5"),), origine="dc:1",
                sport="football") -> AdaptedEvaluation:
    return AdaptedEvaluation(
        schema_version="1", event_id=event, sport=sport,
        competition_id="competition:football:nld:eredivisie",
        scheduled_at=_T + timedelta(hours=5),
        participant_ids=("team:football:nld:a", "team:football:nld:b"),
        observed_at=_OBSERVE, bookmaker="winamax",
        market_id=f"winamax:{event}:{market}", market_type=market, selection=selection,
        bookmaker_odds=Decimal(odds), fair_probability=Decimal(fair),
        probability_low=Decimal(low), probability_high=Decimal(fair),
        uncertainty_status=incertitude, model_version="football.totals.v0",
        model_maturity=maturity, data_quality=Decimal(qualite), calibration_score=None,
        freshness_score=Decimal("0.9"), liquidity_score=None,
        implied_probability_raw=Decimal("0.5556"), no_vig_probability=Decimal("0.5300"),
        edge=Decimal("0.05"), expected_value=Decimal("0.044"), is_boosted=False,
        decision="ABSTAIN", decision_reasons=("MODEL_NOT_SUPPORTED",), warnings=(),
        explanation=AdaptedExplanation((), frozenset(), (), ()),
        source_decision_id=None,
        provenance=MarketProvenance(
            source_event_id="72530852", bookmaker_market_id="bet-2749",
            raw_bet_type=2749, raw_bet_type_name="Nombre de buts",
            market_family=famille, parameters=parametres,
            model_name="football_totals", probability_origin=origine,
            event_label="A - B"))


class _Verdict:
    """Un `CandidateEvaluation` réduit à ce que le classement en lit."""

    def __init__(self, evaluation, statut, raisons=()):
        self.candidate = dataclasses.make_dataclass(
            "C", ["event_id", "market_type", "selection"], frozen=True)(
            evaluation.event_id, evaluation.market_type, evaluation.selection)
        self.status = statut
        self.policy_reasons = tuple(raisons)


def _batch(*evaluations):
    return AdaptedBatch("1", _T, tuple(evaluations), ())


# ══ La politique d'éligibilité est la MÊME que celle du chemin argent ════════
def test_un_candidat_refuse_par_la_politique_n_entre_pas_dans_le_classement():
    """Sur un run réel, un « Rio Ave bat le FC Porto » à +24 % d'edge remontait en
    tête du classement alors que la politique venait de l'écarter en
    LOW_DATA_QUALITY : le modèle y annonçait `form_insufficient` pour les deux
    équipes, donc sa probabilité ne disait rien des équipes."""
    bon, mauvais = _evaluation(), _evaluation(selection="under", odds="2.00")
    review = construire_review(
        _batch(bon, mauvais), freshness_at=_T,
        policy_evaluations=[
            _Verdict(bon, CandidateStatus.REVIEW_ONLY),
            _Verdict(mauvais, CandidateStatus.REJECTED, ("LOW_DATA_QUALITY",))])

    classes = [r.candidate.selection for r in review.global_ranking]
    assert classes == ["over"]
    assert review.ecartes_par_politique == (("TOTALS(line=2.5)/under", ("LOW_DATA_QUALITY",)),)


def test_un_candidat_que_la_politique_n_a_pas_jugé_n_entre_pas_non_plus():
    """Mieux vaut ne pas classer que classer sans jugement."""
    juge, inconnu = _evaluation(), _evaluation(selection="under")
    review = construire_review(_batch(juge, inconnu), freshness_at=_T,
                               policy_evaluations=[_Verdict(juge, CandidateStatus.REVIEW_ONLY)])

    assert [r.candidate.selection for r in review.global_ranking] == ["over"]
    assert review.ecartes_par_politique[0][1] == ("NOT_EVALUATED_BY_POLICY",)


# ══ §5 — une borne non estimée n'est pas une borne ══════════════════════════
def test_une_borne_non_estimee_rend_le_candidat_non_comparable():
    """`NOT_ESTIMATED` veut dire que l'incertitude n'est pas mesurée. Reprendre la
    probabilité centrale comme minorant est exactement le faux substitut que tout
    ce mécanisme existe pour supprimer."""
    sans_borne = _evaluation(incertitude="NOT_ESTIMATED", low="0.58")

    candidat = candidat_depuis_evaluation(sans_borne, freshness_at=_T)
    assert candidat.probability_low is None

    review = construire_review(_batch(sans_borne), freshness_at=_T)
    assert review.global_ranking == ()
    assert len(review.non_comparables) == 1
    assert any("NOT_ESTIMATED" in m for m in review.non_comparables[0].reasons)


def test_le_candidat_non_comparable_reste_visible_avec_son_motif():
    """« Pas comparable » est une réponse. Le faire disparaître transformerait une
    incertitude non mesurée en absence d'opportunité."""
    review = construire_review(
        _batch(_evaluation(incertitude="NOT_ESTIMATED", low="0.58")), freshness_at=_T)

    r = review.non_comparables[0]
    assert r.comparability is Comparability.NOT_COMPARABLE
    assert r.status is ProductStatus.NOT_COMPARABLE
    assert r.candidate.bookmaker_odds == 1.80      # la prédiction reste lisible


# ══ §4 — REVIEW n'est jamais ACTIONABLE ═════════════════════════════════════
def test_un_modele_experimental_ne_peut_pas_etre_actionable():
    review = construire_review(_batch(_evaluation()), freshness_at=_T)

    assert len(review.review) == 1 and review.actionable == ()
    assert review.review[0].status is ProductStatus.REVIEW


def test_seule_la_maturite_SUPPORTED_ouvre_ACTIONABLE():
    """Ce module LIT la maturité, il ne la produit pas. Être premier du classement
    n'a jamais rendu un modèle misable."""
    review = construire_review(_batch(_evaluation(maturity="SUPPORTED")), freshness_at=_T)

    assert len(review.actionable) == 1 and review.review == ()


# ══ §3 — le meilleur marché d'une rencontre ═════════════════════════════════
def test_le_meilleur_marche_peut_ne_pas_etre_le_vainqueur():
    """La mesure produit du chantier : si elle vaut toujours zéro, évaluer cinq
    familles n'aura rien changé à ce qu'on montre."""
    vainqueur = _evaluation(market="MATCH_WINNER", famille="MATCH_WINNER", parametres=(),
                            selection="home", odds="1.50", fair="0.60", low="0.55")
    total = _evaluation(odds="2.60", fair="0.58", low="0.53")
    review = construire_review(_batch(vainqueur, total), freshness_at=_T)

    meilleur = review.meilleur_de("72530852")
    assert meilleur is not None and meilleur.candidate.selection == "over"
    assert review.evenements_dont_le_meilleur_n_est_pas_le_vainqueur == ("72530852",)


def test_les_deux_cotes_d_un_meme_marche_ne_font_pas_deux_opportunites():
    """« Plus de 2,5 » et « Moins de 2,5 » décrivent la même opinion vue des deux
    bords : au plus l'un des deux peut avoir une espérance favorable."""
    review = construire_review(
        _batch(_evaluation(selection="over"), _evaluation(selection="under", odds="2.20")),
        freshness_at=_T)

    assert len(review.par_evenement["72530852"]) == 1


# ══ §9 — la provenance voyage jusqu'au bout ═════════════════════════════════
def test_le_candidat_porte_la_provenance_complete_du_marche():
    """Chaque chiffre affiché doit pouvoir être remonté jusqu'à la ligne exacte du
    bookmaker qui l'a produit."""
    c = candidat_depuis_evaluation(_evaluation(), freshness_at=_T)

    assert (c.source_event_id, c.market_source_id, c.bet_type) == ("72530852", "bet-2749", 2749)
    assert c.bet_type_name == "Nombre de buts"
    assert c.parameters == {"line": "2.5"} and c.probability_origin == "dc:1"
    assert c.observed_at == _OBSERVE and c.freshness is not None


def test_la_fraicheur_se_mesure_a_la_fin_de_l_acquisition_pas_avant_le_scan():
    """Le point-in-time du modèle précède le scan par construction : mesurer
    l'âge d'une cote contre lui le rend négatif, et TOUS les candidats
    deviennent non comparables — mesuré sur 262 sélections réelles."""
    avant_le_scan = _OBSERVE - timedelta(minutes=1)

    assert candidat_depuis_evaluation(_evaluation(), freshness_at=avant_le_scan).freshness is None
    assert candidat_depuis_evaluation(_evaluation(), freshness_at=_T).freshness is not None


# ══ La qualité de données décide, pas l'espérance ═══════════════════════════
def test_une_prediction_aux_entrees_incompletes_n_est_pas_comparable():
    """Mesuré en mi-août sur la Primeira Liga : une et deux journées jouées, le
    modèle déclare `form_insufficient` pour les deux équipes et tire ses forces
    vers la moyenne de la ligue. Sa probabilité ne décrit plus les équipes mais
    le championnat — et le classement en faisait un « +86 % d'espérance ».
    """
    from src.agents.quant.betting_engine.value_engine.bet_policy import (
        default_bet_decision_policy,
    )

    seuil = float(default_bet_decision_policy().min_data_quality)
    faible = _evaluation(qualite=str(seuil - 0.2), odds="6.25", fair="0.55", low="0.50")

    review = construire_review(_batch(faible), freshness_at=_T)

    assert review.global_ranking == ()
    assert any("DATA_QUALITY_INSUFFICIENT" in m
               for m in review.non_comparables[0].reasons)


def test_le_refus_vient_de_la_qualite_jamais_de_la_taille_de_l_esperance():
    """Une grosse espérance peut être réelle : elle ne prouve rien, ni dans un
    sens ni dans l'autre. Deux candidats de MÊME qualité suffisante, l'un à
    espérance énorme, restent tous deux comparables."""
    enorme = _evaluation(odds="9.00", fair="0.30", low="0.25", selection="over")
    modeste = _evaluation(odds="1.80", fair="0.58", low="0.53", selection="under")

    review = construire_review(_batch(enorme, modeste), freshness_at=_T)

    assert len(review.non_comparables) == 0
    assert {r.candidate.selection for r in review.global_ranking} <= {"over", "under"}
