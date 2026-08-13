"""Corrélation intra-événement : au plus UNE mise par distribution et par match.

« Domicile gagne », « plus de 2,5 buts », « double chance 1N », « score exact
2-1 » d'un même match sortent tous de la MÊME matrice Dixon-Coles. Ce ne sont pas
quatre paris : c'est quatre lectures d'une seule opinion. Les miser ensemble ne
diversifie rien — cela quadruple l'exposition à une seule erreur de modèle, tout
en donnant l'apparence d'un portefeuille réparti.

La règle est conservatrice ET non inventive : on ne fabrique aucune matrice de
corrélation, on refuse simplement de cumuler ce qu'on ne sait pas décorréler. La
REVUE, elle, reste complète : voir plusieurs angles d'un match est utile ; les
miser tous ne l'est pas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.advisor.domain.candidates import (
    CandidateBet,
    CandidateEvaluation,
    CandidateStatus,
)
from src.agents.quant.advisor.domain.enums import MaturityPolicy, RiskProfile
from src.agents.quant.advisor.domain.money import ONE
from src.agents.quant.advisor.domain.requests import RecommendationRequest
from src.agents.quant.advisor.policy.reason_codes import CORRELATED_SAME_ORIGIN
from src.agents.quant.advisor.portfolio.allocation import allocate_lines
from src.agents.quant.advisor.portfolio.constraints import load_portfolio_caps
from src.agents.quant.advisor.recommendation.simple import load_sizing_profiles

_T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
_SIZING = load_sizing_profiles()["BALANCED"]
_CAPS = load_portfolio_caps()["BALANCED"]
_ORIGINE = "dixon_coles:score_matrix:event:1"


def _cand(cid, event, *, origine=None, marche="MATCH_WINNER", selection="home",
          p_low=Decimal("0.60"), odds=Decimal("2.00")):
    low, high = p_low, p_low + Decimal("0.05")
    fair = (low + high) / 2
    return CandidateBet(
        candidate_id=cid, event_id=event, sport="football", competition_id="comp:1",
        scheduled_at=_T, bookmaker="winamax", market_id=f"m:{cid}", market_type=marche,
        selection=selection, bookmaker_odds=odds, fair_probability=fair, probability_low=low,
        probability_high=high, fair_odds=Decimal("1.90"), implied_probability=Decimal("0.50"),
        expected_value_mean=fair * odds - ONE, expected_value_low=low * odds - ONE,
        edge_mean=Decimal("0.05"), edge_low=Decimal("0.03"), model_version="m.v1",
        model_maturity="SUPPORTED", calibration_score=Decimal("0.75"),
        data_quality=Decimal("1.0"), freshness_score=Decimal("0.90"), liquidity_score=None,
        max_stake=None, max_payout=None, is_boosted=False,
        participant_ids=(f"team:{event}:a",), exposure_keys=frozenset({f"event:{event}"}),
        warnings=(), explanation_ref="e", source_decision_id=None,
        probability_origin=origine)


def _eval(cand):
    return CandidateEvaluation(cand, CandidateStatus.ELIGIBLE, (), Decimal("1"),
                               {"reliability_component": Decimal("0.75")})


def _request(*, bankroll="100", max_selections=5):
    return RecommendationRequest(
        request_id="r", decision_time=_T, bankroll=Decimal(bankroll), currency="EUR",
        allowed_sports=None, allowed_competitions=None, allowed_bookmakers=None,
        allowed_market_types=None, target_total_odds=None, max_total_stake=None,
        max_selections=max_selections, max_portfolios=1, allow_singles=True,
        allow_combos=False, max_combo_legs=2, risk_profile=RiskProfile.BALANCED,
        maturity_policy=MaturityPolicy.SUPPORTED_ONLY, ranking_profile="balanced_v1",
        excluded_event_ids=frozenset(), excluded_participant_ids=frozenset(),
        excluded_market_types=frozenset())


def _allouer(candidats, **kw):
    return allocate_lines([_eval(c) for c in candidats], _request(**kw),
                          sizing=_SIZING, caps=_CAPS, bankroll=Decimal("100"))


# ── Une seule mise par distribution et par événement ─────────────────────────

def test_une_seule_selection_misee_par_origine_et_par_evenement():
    """Les quatre marchés du même match sortent de la même matrice : un seul est
    misé, les trois autres sont écartés avec un motif nommé."""
    marches = [
        _cand("c1", "ev:1", origine=_ORIGINE, marche="MATCH_WINNER", selection="home"),
        _cand("c2", "ev:1", origine=_ORIGINE, marche="TOTALS", selection="over"),
        _cand("c3", "ev:1", origine=_ORIGINE, marche="DOUBLE_CHANCE", selection="home_or_draw"),
        _cand("c4", "ev:1", origine=_ORIGINE, marche="EXACT_SCORE", selection="2:1"),
    ]
    allocation = _allouer(marches)

    assert len(allocation.lines) == 1
    assert allocation.lines[0].evaluation.candidate.candidate_id == "c1"
    ecartes = dict(allocation.dropped)
    assert set(ecartes) == {"c2", "c3", "c4"}
    assert set(ecartes.values()) == {CORRELATED_SAME_ORIGIN}


def test_le_motif_distingue_la_correlation_d_un_refus_de_valeur():
    """Le candidat était bon : c'est sa DÉPENDANCE qui l'écarte. Un rapport doit
    pouvoir le dire, sinon on croit à un problème de valeur."""
    allocation = _allouer([
        _cand("c1", "ev:1", origine=_ORIGINE),
        _cand("c2", "ev:1", origine=_ORIGINE, marche="TOTALS", selection="over"),
    ])
    assert allocation.dropped == [("c2", CORRELATED_SAME_ORIGIN)]
    assert CORRELATED_SAME_ORIGIN not in ("STAKE_NON_POSITIVE", "STAKE_BELOW_MIN")


# ── Ce que la règle ne doit PAS restreindre ──────────────────────────────────

def test_deux_evenements_restent_independants():
    """La contrainte est intra-événement. Deux matchs différents, même méthode,
    restent deux paris distincts."""
    allocation = _allouer([
        _cand("c1", "ev:1", origine="dixon_coles:score_matrix:ev:1"),
        _cand("c2", "ev:2", origine="dixon_coles:score_matrix:ev:2"),
    ])
    assert len(allocation.lines) == 2
    assert not allocation.dropped


def test_deux_origines_differentes_ne_sont_pas_fusionnees():
    """Même événement, mais deux distributions réellement distinctes (un modèle
    de buts et un modèle de cartons, par exemple) : rien ne justifie de les
    traiter comme une seule opinion."""
    allocation = _allouer([
        _cand("c1", "ev:1", origine="dixon_coles:score_matrix:ev:1"),
        _cand("c2", "ev:1", origine="autre_modele:ev:1", marche="CARDS", selection="over"),
    ])
    assert len(allocation.lines) == 2
    assert not allocation.dropped


def test_une_origine_non_declaree_ne_contraint_rien():
    """`None` veut dire « l'appelant ne l'a pas dite », pas « elles sont liées ».
    Inventer une dépendance non déclarée changerait le comportement money existant
    sur la foi d'une supposition — c'est exactement ce qu'on refuse de faire."""
    allocation = _allouer([
        _cand("c1", "ev:1"), _cand("c2", "ev:1", marche="TOTALS", selection="over"),
    ])
    assert len(allocation.lines) == 2
    assert not allocation.dropped


def test_la_revue_n_est_pas_touchee():
    """La contrainte vit dans l'ALLOCATION, pas dans l'évaluation : plusieurs
    angles du même match restent tous évaluables et affichables."""
    import inspect

    from src.agents.quant.advisor.policy import eligibility

    assert CORRELATED_SAME_ORIGIN not in inspect.getsource(eligibility)


# ── L'ordre du classement décide lequel survit ───────────────────────────────

def test_c_est_le_mieux_classe_qui_est_retenu():
    """Le glouton parcourt le classement : le premier passé est le seul servi.
    Ce n'est pas un choix arbitraire, c'est le classement qui tranche."""
    ordre = [
        _cand("meilleur", "ev:1", origine=_ORIGINE, marche="TOTALS", selection="over"),
        _cand("suivant", "ev:1", origine=_ORIGINE, marche="MATCH_WINNER"),
    ]
    allocation = _allouer(ordre)
    assert [l.evaluation.candidate.candidate_id for l in allocation.lines] == ["meilleur"]


def test_une_ancre_correlee_rend_l_alternative_absente():
    """Si l'ancre d'une alternative est elle-même corrélée à ce qui précède,
    l'alternative n'existe pas — elle n'est pas silencieusement remplacée."""
    candidats = [_cand("c1", "ev:1", origine=_ORIGINE),
                 _cand("c2", "ev:1", origine=_ORIGINE, marche="TOTALS", selection="over")]
    evals = [_eval(c) for c in candidats]
    # L'ancre c2 passe en tête : rien avant elle, donc elle est servie.
    premiere = allocate_lines(evals, _request(), sizing=_SIZING, caps=_CAPS,
                              bankroll=Decimal("100"), anchor_id="c2")
    assert premiere is not None
    assert premiere.lines[0].evaluation.candidate.candidate_id == "c2"
    assert dict(premiere.dropped) == {"c1": CORRELATED_SAME_ORIGIN}
