"""Classement REVUE multi-sport / multi-marché — comparer, sans favoriser.

Ce que ces tests protègent, dans l'ordre :

1. rien n'est favorisé — ni `MATCH_WINNER`, ni le football, ni les grosses cotes,
   ni les probabilités élevées ;
2. ce qui manque n'est jamais remplacé : `NOT_COMPARABLE` plutôt qu'un zéro ;
3. le classement ne promeut aucune maturité ;
4. deux côtés d'un même marché ne sont pas deux opportunités.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.markets.review_ranking import (
    Comparability,
    ProductStatus,
    ReviewCandidate,
    best_market_per_event,
    classement_global,
    comparabilite,
    esperance_prudente,
    evaluer,
    meilleure_par_marche,
    score_prudent,
)
from src.agents.quant.betting_engine.value_engine.settlement import OutcomeShare, Settlement


def _c(**kw) -> ReviewCandidate:
    base = dict(
        source_event_id="e1", sport="football", competition="comp:1",
        family=MarketFamily.TOTALS, parameters={"line": 2.5}, context={},
        selection="over", bookmaker_odds=2.10, implied_probability=0.4762,
        vig_adjusted_probability=0.47, fair_probability=0.60, probability_low=0.55,
        expected_value=0.26, maturity="EXPERIMENTAL", freshness=0.9,
        data_quality=0.95, probability_origin="dixon_coles:e1")
    base.update(kw)
    return ReviewCandidate(**base)


# ── Comparabilité : l'absence se dit ─────────────────────────────────────────

@pytest.mark.parametrize("champ,motif", [
    ("probability_low", "probability_low"), ("fair_probability", "probabilité de modèle"),
    ("bookmaker_odds", "cote"), ("freshness", "fraîcheur"),
    ("data_quality", "qualité"), ("maturity", "maturité"),
])
def test_une_grandeur_indispensable_absente_rend_non_comparable(champ, motif):
    statut, motifs = comparabilite(_c(**{champ: None}))
    assert statut is Comparability.NOT_COMPARABLE
    assert any(motif in m for m in motifs), motifs


def test_un_none_ne_devient_jamais_zero():
    """Un `None` transformé en 0 classerait le candidat en dernier au lieu de le
    sortir du classement. Deux choses très différentes, dont une seule est vraie."""
    r = evaluer([_c(probability_low=None)])[0]
    assert r.status is ProductStatus.NOT_COMPARABLE
    assert r.score is None and r.expected_value_low is None


def test_une_cote_invalide_n_est_pas_comparable():
    assert comparabilite(_c(bookmaker_odds=1.0))[0] is Comparability.NOT_COMPARABLE


# ── Le score est prudent ─────────────────────────────────────────────────────

def test_le_score_repose_sur_la_borne_basse_et_non_sur_le_point():
    """Deux candidats de même probabilité centrale, bornés différemment : c'est
    le mieux borné qui passe devant."""
    large = _c(probability_low=0.45)
    serre = _c(probability_low=0.58)
    assert score_prudent(serre) > score_prudent(large)
    assert esperance_prudente(serre) > esperance_prudente(large)


def test_une_esperance_prudente_negative_ne_vaut_aucun_score():
    """Le plancher du profil Advisor : une valeur pire-cas négative n'est pas une
    petite valeur, c'est aucune valeur."""
    assert esperance_prudente(_c(probability_low=0.30)) < 0
    assert score_prudent(_c(probability_low=0.30)) == Decimal("0.000000")


def test_l_esperance_prudente_respecte_le_remboursement():
    """Sur un marché à push, la part remboursée est une propriété du MARCHÉ : la
    borner ne la déplace pas. La masse retirée à l'issue gagnante rejoint la
    perte — on ne rend pas un pari plus sûr en le bornant."""
    parts = (OutcomeShare(0.45, Settlement.WIN), OutcomeShare(0.27, Settlement.PUSH),
             OutcomeShare(0.28, Settlement.LOSS))
    avec_push = _c(family=MarketFamily.DRAW_NO_BET, parameters={}, selection="home",
                   fair_probability=0.6164, probability_low=0.55, settlement_shares=parts)
    sans_push = _c(fair_probability=0.6164, probability_low=0.55)
    assert esperance_prudente(avec_push) < esperance_prudente(sans_push)


# ── Rien n'est favorisé ──────────────────────────────────────────────────────

def test_ni_le_sport_ni_la_famille_n_entrent_dans_le_score():
    """Le score ne lit ni le nom du sport, ni celui de la famille."""
    reference = score_prudent(_c())
    for sport in ("tennis", "basketball", "baseball", "hockey"):
        assert score_prudent(_c(sport=sport)) == reference
    for famille in (MarketFamily.MATCH_WINNER, MarketFamily.DOUBLE_CHANCE,
                    MarketFamily.EXACT_SCORE, MarketFamily.DRAW_NO_BET):
        assert score_prudent(_c(family=famille)) == reference


def test_une_grosse_cote_ne_suffit_pas_a_passer_devant():
    """Cote élevée mais probabilité mal bornée contre cote modeste bien bornée :
    c'est l'espérance prudente qui tranche, pas la cote."""
    grosse = _c(selection="a", bookmaker_odds=8.0, fair_probability=0.14,
                probability_low=0.10, source_event_id="e2")
    modeste = _c(selection="b", bookmaker_odds=1.75, fair_probability=0.62,
                 probability_low=0.60, source_event_id="e3")
    assert esperance_prudente(grosse) < esperance_prudente(modeste)
    classement = classement_global([grosse, modeste])
    assert classement[0].candidate.selection == "b"


def test_une_probabilite_elevee_ne_suffit_pas():
    """Probabilité haute mais cote qui ne la paie pas : aucune valeur."""
    haute = _c(fair_probability=0.92, probability_low=0.88, bookmaker_odds=1.05)
    assert esperance_prudente(haute) < 0


def test_le_classement_est_deterministe_et_neutre_au_depart():
    """À score égal, le départage est l'identifiant du marché — jamais le sport."""
    a = _c(source_event_id="e1", sport="tennis", selection="x")
    b = _c(source_event_id="e2", sport="football", selection="x")
    ordre = [r.candidate.source_event_id for r in classement_global([b, a])]
    assert ordre == sorted(ordre)


# ── Une seule sélection économique par marché ────────────────────────────────

def test_les_deux_cotes_d_un_marche_ne_font_pas_deux_opportunites():
    over = _c(selection="over", fair_probability=0.60, probability_low=0.55)
    under = _c(selection="under", fair_probability=0.40, probability_low=0.35,
               bookmaker_odds=1.80)
    retenus = meilleure_par_marche(evaluer([over, under]))
    assert len(retenus) == 1
    assert retenus[0].candidate.selection == "over"


def test_deux_lignes_differentes_restent_deux_marches():
    a = _c(parameters={"line": 2.5})
    b = _c(parameters={"line": 3.5}, fair_probability=0.40, probability_low=0.36)
    assert len({r.candidate.market_key for r in evaluer([a, b])}) == 2
    assert len(meilleure_par_marche(evaluer([a, b]))) == 2


# ── BEST_MARKET_PER_EVENT ────────────────────────────────────────────────────

def test_le_meilleur_marche_d_un_evenement_n_est_pas_forcement_le_vainqueur():
    """L'exigence produit : pouvoir dire « le meilleur angle de ce match n'est pas
    le vainqueur »."""
    vainqueur = _c(family=MarketFamily.MATCH_WINNER, parameters={}, selection="home",
                   bookmaker_odds=1.90, fair_probability=0.54, probability_low=0.50)
    total = _c(family=MarketFamily.TOTALS, parameters={"line": 2.5}, selection="over",
               bookmaker_odds=2.10, fair_probability=0.60, probability_low=0.57)
    par_evenement = best_market_per_event([vainqueur, total])

    lignes = par_evenement["e1"]
    assert [l.event_rank for l in lignes] == [1, 2]
    assert lignes[0].candidate.family is MarketFamily.TOTALS
    assert lignes[0].candidate.family is not MarketFamily.MATCH_WINNER


def test_chaque_evenement_a_son_propre_classement():
    a = _c(source_event_id="e1")
    b = _c(source_event_id="e2", probability_low=0.58)
    par_evenement = best_market_per_event([a, b])
    assert set(par_evenement) == {"e1", "e2"}
    assert all(l[0].event_rank == 1 for l in par_evenement.values())


def test_le_classement_global_fusionne_les_evenements():
    """Valeurs choisies DANS la bande discriminante du profil (`ev_floor`=0,
    `ev_cap`=0,15) : au-delà, le profil sature volontairement."""
    a = _c(source_event_id="e1", probability_low=0.50)      # EV_low = 0,050
    b = _c(source_event_id="e2", probability_low=0.53)      # EV_low = 0,113
    global_ = classement_global([a, b])
    assert [r.global_rank for r in global_] == [1, 2]
    assert global_[0].candidate.source_event_id == "e2"      # mieux borné


def test_le_profil_sature_au_dela_de_son_plafond():
    """Propriété EXISTANTE de l'échelle Advisor, verrouillée ici : au-delà de
    `ev_cap`, une espérance prudente supérieure ne donne pas un meilleur score.
    Ce n'est pas un défaut — c'est le refus de récompenser sans borne un chiffre
    que le modèle n'estime pas si finement."""
    from src.agents.quant.advisor.ranking.profiles import load_ranking_profiles

    plafond = float(load_ranking_profiles()["balanced_v1"].ev_cap)
    # La COTE fait varier l'espérance, pas la probabilité : depuis que le score
    # porte un terme de probabilité, faire varier `probability_low` déplacerait
    # DEUX facteurs à la fois et ce test ne dirait plus rien de la saturation.
    haut = _c(probability_low=0.60, bookmaker_odds=2.10)       # EV_low = 0,26
    tres_haut = _c(probability_low=0.60, bookmaker_odds=2.60)  # EV_low > 0,26
    assert esperance_prudente(haut) > plafond
    assert esperance_prudente(tres_haut) > esperance_prudente(haut)
    assert score_prudent(tres_haut) == score_prudent(haut)


def test_a_esperance_saturee_la_probabilite_departage():
    """Le pendant du test précédent, et la raison d'être de la correction.

    La saturation de la VALEUR est délibérée. Ce qui ne l'était pas : une fois
    saturée, plus rien ne départageait deux sélections — l'ordre retombait sur
    la qualité des données. Sur un run réel, les cinq sélections affichées
    avaient toutes `value = 1`, et l'utilisateur a vu du hasard.
    """
    from src.agents.quant.advisor.ranking.profiles import load_ranking_profiles

    from src.agents.quant.betting_engine.markets.review_ranking import (
        Comparability, Posture, ProductStatus, RankedCandidate, _trier,
    )
    from decimal import Decimal as D

    sur = _c(source_event_id="sur", probability_low=0.78,
             probability_low_status="ESTIMATED", bookmaker_odds=2.10)
    risque = _c(source_event_id="risque", probability_low=0.60,
                probability_low_status="ESTIMATED", bookmaker_odds=3.40)
    plafond = float(load_ranking_profiles()["balanced_v1"].ev_cap)
    assert esperance_prudente(sur) > plafond
    assert esperance_prudente(risque) > plafond
    # Le SCORE ne les distingue plus : la valeur sature et la probabilité n'y
    # entre pas. C'est l'ORDRE qui porte la sûreté.
    assert score_prudent(sur) == score_prudent(risque)

    rangs = [RankedCandidate(risque, Comparability.COMPARABLE, ProductStatus.REVIEW,
                             D("0.5"), D(str(esperance_prudente(risque)))),
             RankedCandidate(sur, Comparability.COMPARABLE, ProductStatus.REVIEW,
                             D("0.5"), D(str(esperance_prudente(sur))))]
    classe = _trier(rangs, Posture.SAFETY_FIRST)
    assert classe[0].candidate.probability_low == 0.78, (
        "à valeur saturée, la sélection la plus probable doit passer devant")


# ── Aucune promotion ─────────────────────────────────────────────────────────

def test_le_premier_du_classement_reste_experimental():
    """Être premier n'a jamais rendu personne misable."""
    global_ = classement_global([_c(maturity="EXPERIMENTAL")])
    assert global_[0].global_rank == 1
    assert global_[0].status is ProductStatus.REVIEW


def test_la_maturite_est_consommee_jamais_produite():
    """Le module LIT le vocabulaire de maturité ; il ne doit jamais toucher au
    ledger qui la décide, ni à l'évaluateur qui la calcule."""
    import inspect

    from src.agents.quant.betting_engine.markets import review_ranking

    source = inspect.getsource(review_ranking)
    for interdit in ("resolve_market_status", "ModelSupportDecision",
                     "evaluate_maturity", "support_status"):
        assert interdit not in source, interdit


def test_un_supported_est_actionable_sans_changer_de_score_relatif():
    """La maturité change le STATUT et la fiabilité, jamais l'ordre des mesures."""
    exp = _c(maturity="EXPERIMENTAL")
    sup = _c(maturity="SUPPORTED")
    assert evaluer([exp])[0].status is ProductStatus.REVIEW
    assert evaluer([sup])[0].status is ProductStatus.ACTIONABLE
    assert score_prudent(sup) > score_prudent(exp)          # fiabilité, pas promotion
    assert esperance_prudente(sup) == esperance_prudente(exp)
