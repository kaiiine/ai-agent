"""Ranking Engine (Lot 5, ADR-ADV-005). Fixtures SUPPORTED/ELIGIBLE (aucun modèle
réel n'est SUPPORTED en V1 ; le moteur est néanmoins construit et testé).

Couvre : monotonie EV, pénalités incertitude/fraîcheur, profils conservateur vs
agressif, déterminisme, tie-break lexical, exclusion des REVIEW_ONLY, bornes,
0 autorisé uniquement où l'ADR le prévoit, donnée manquante (rejet vs fallback
documenté, jamais 0 silencieux), indépendance à l'ordre, aucun floor générique.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agents.quant.advisor.domain.candidates import CandidateBet, CandidateEvaluation
from src.agents.quant.advisor.domain.enums import CandidateStatus
from src.agents.quant.advisor.policy import reason_codes as R
from src.agents.quant.advisor.ranking import RankingProfile, load_ranking_profiles, rank
from src.agents.quant.advisor.ranking.profiles import OPTIONAL, REQUIRED

_KO = datetime(2026, 8, 1, 17, tzinfo=timezone.utc)
_REQS = {"value": REQUIRED, "quality": REQUIRED, "freshness": REQUIRED,
         "reliability": REQUIRED, "liquidity": OPTIONAL}


def _profile(**kw) -> RankingProfile:
    base = dict(
        name="test", requirements=_REQS, ev_floor=Decimal("0.00"), ev_cap=Decimal("0.20"),
        supported_baseline=Decimal("0.60"), liquidity_unknown_default=Decimal("0.80"),
        uncertainty_weight=Decimal("0.80"), concentration_weight=Decimal("0.40"))
    base.update(kw)
    return RankingProfile(**base)


def _cand(cid="c1", event="e1", ev_low=Decimal("0.10"), width=Decimal("0.10"),
          freshness=Decimal("0.90"), data_quality=Decimal("1.0"), calibration=None,
          liquidity=None, maturity="SUPPORTED", exposure=None) -> CandidateBet:
    low = Decimal("0.50")
    high = low + width
    fair = (low + high) / 2
    return CandidateBet(
        candidate_id=cid, event_id=event, sport="football", competition_id="comp:1",
        scheduled_at=_KO, bookmaker="winamax", market_id="m", market_type="MATCH_WINNER",
        selection="home", bookmaker_odds=Decimal("2.10"), fair_probability=fair,
        probability_low=low, probability_high=high, fair_odds=Decimal("2.00"),
        implied_probability=Decimal("0.4762"), expected_value_mean=ev_low, expected_value_low=ev_low,
        edge_mean=Decimal("0.02"), edge_low=Decimal("0.02"), model_version="m.v1",
        model_maturity=maturity, calibration_score=calibration, data_quality=data_quality,
        freshness_score=freshness, liquidity_score=liquidity, max_stake=None, max_payout=None,
        is_boosted=False, participant_ids=("team:a", "team:b"),
        exposure_keys=exposure or frozenset({f"event:{event}"}),
        warnings=(), explanation_ref="expl", source_decision_id=None)


def _elig(cand: CandidateBet) -> CandidateEvaluation:
    return CandidateEvaluation(cand, CandidateStatus.ELIGIBLE, (), None, {})


def _ranked_ids(result):
    return [e.candidate.candidate_id for e in result.ranked]


# ── Monotonie / pénalités ─────────────────────────────────────────────────────
def test_score_monotone_with_ev_low():
    hi = _elig(_cand("hi", "e1", ev_low=Decimal("0.12")))
    lo = _elig(_cand("lo", "e2", ev_low=Decimal("0.04")))
    res = rank([lo, hi], profile=_profile())
    assert _ranked_ids(res) == ["hi", "lo"]
    assert res.ranked[0].ranking_score > res.ranked[1].ranking_score


def test_uncertainty_penalty_lowers_score():
    tight = _elig(_cand("tight", "e1", width=Decimal("0.02")))
    wide = _elig(_cand("wide", "e2", width=Decimal("0.40")))
    res = rank([wide, tight], profile=_profile())
    assert _ranked_ids(res) == ["tight", "wide"]


def test_freshness_lowers_score():
    fresh = _elig(_cand("fresh", "e1", freshness=Decimal("0.95")))
    stale = _elig(_cand("stale", "e2", freshness=Decimal("0.40")))
    res = rank([stale, fresh], profile=_profile())
    assert _ranked_ids(res) == ["fresh", "stale"]


def test_conservative_vs_aggressive_rank_differently():
    profiles = load_ranking_profiles()
    a = _elig(_cand("A", "e1", ev_low=Decimal("0.10"), width=Decimal("0.30")))  # EV haut, incertain
    b = _elig(_cand("B", "e2", ev_low=Decimal("0.06"), width=Decimal("0.02")))  # EV moindre, sûr
    assert _ranked_ids(rank([a, b], profile=profiles["aggressive_v1"])) == ["A", "B"]
    assert _ranked_ids(rank([a, b], profile=profiles["conservative_v1"])) == ["B", "A"]


# ── Déterminisme / tie-break / ordre ──────────────────────────────────────────
def test_deterministic():
    cands = [_elig(_cand(f"c{i}", f"e{i}", ev_low=Decimal(f"0.0{i}"))) for i in range(1, 6)]
    r1 = rank(cands, profile=_profile())
    r2 = rank(cands, profile=_profile())
    assert _ranked_ids(r1) == _ranked_ids(r2)
    assert [e.ranking_score for e in r1.ranked] == [e.ranking_score for e in r2.ranked]


def test_lexical_tie_break():
    # Scores identiques (événements distincts, concentration nulle) -> candidate_id lexical.
    z = _elig(_cand("z", "e1"))
    a = _elig(_cand("a", "e2"))
    assert _ranked_ids(rank([z, a], profile=_profile())) == ["a", "z"]


def test_input_order_independence_with_concentration():
    # Deux candidats même événement (exposition partagée -> concentration) + un tiers.
    shared = frozenset({"event:e1", "participant:team:a"})
    c1 = _elig(_cand("c1", "e1", ev_low=Decimal("0.12"), exposure=shared))
    c2 = _elig(_cand("c2", "e1", ev_low=Decimal("0.10"), exposure=shared))
    c3 = _elig(_cand("c3", "e3", ev_low=Decimal("0.11")))
    ordered = rank([c1, c2, c3], profile=_profile())
    for _ in range(8):
        shuffled = [c1, c2, c3][:]
        random.shuffle(shuffled)
        s = rank(shuffled, profile=_profile())
        assert _ranked_ids(s) == _ranked_ids(ordered)          # même ordre
        assert [e.ranking_score for e in s.ranked] == [e.ranking_score for e in ordered.ranked]


# ── Frontière : ne classe QUE ELIGIBLE ────────────────────────────────────────
def test_review_only_and_rejected_excluded():
    elig = _elig(_cand("e", "e1"))
    review = CandidateEvaluation(_cand("r", "e2"), CandidateStatus.REVIEW_ONLY,
                                 (R.EXPERIMENTAL_REVIEW_ONLY,), None, {})
    rejected = CandidateEvaluation(_cand("x", "e3"), CandidateStatus.REJECTED,
                                   (R.MODEL_NOT_SUPPORTED,), None, {})
    res = rank([review, elig, rejected], profile=_profile())
    assert _ranked_ids(res) == ["e"]                            # review/rejected ignorés
    assert res.non_rankable == ()


# ── Bornes / config ───────────────────────────────────────────────────────────
def test_profile_out_of_bounds_rejected():
    with pytest.raises(ValueError):
        _profile(ev_cap=Decimal("0.00"))                        # ev_cap <= ev_floor
    with pytest.raises(ValueError):
        _profile(supported_baseline=Decimal("1.0"))             # hors ]0,1[


def test_default_profiles_load():
    profiles = load_ranking_profiles()
    assert {"conservative_v1", "balanced_v1", "aggressive_v1"} <= set(profiles)
    assert isinstance(profiles["balanced_v1"].uncertainty_weight, Decimal)


# ── 0 autorisé uniquement où l'ADR le prévoit ────────────────────────────────
def test_value_component_zero_nullifies_intentionally():
    # ev_low == ev_floor (0) et intervalle nul -> value_component 0, score 0 (légitime).
    c = _elig(_cand("z", "e1", ev_low=Decimal("0.00"), width=Decimal("0.00")))
    res = rank([c], profile=_profile())
    comps = res.ranked[0].ranking_components
    assert comps["value_component"] == Decimal("0")
    assert res.ranked[0].ranking_score == Decimal("0")          # 0 vient d'un composant qui l'autorise


def test_no_generic_floor_applied():
    # value_component petit mais non nul reste tel quel (aucun plancher type 0.05).
    c = _elig(_cand("s", "e1", ev_low=Decimal("0.001"), width=Decimal("0.00")))
    comps = rank([c], profile=_profile()).ranked[0].ranking_components
    assert comps["value_component"] == Decimal("0.001") / Decimal("0.20")   # 0.005 exact, non floored


# ── Donnée manquante : rejet vs fallback documenté, jamais 0 silencieux ───────
def test_missing_freshness_is_non_rankable_not_zero():
    c = _elig(_cand("f", "e1", freshness=None))                 # REQUIRED absent
    res = rank([c], profile=_profile())
    assert res.ranked == ()
    assert res.non_rankable[0].status is CandidateStatus.REJECTED
    assert res.non_rankable[0].policy_reasons == (R.RANKING_MISSING_FRESHNESS,)


def test_missing_liquidity_uses_conservative_default_not_zero_or_one():
    c = _elig(_cand("l", "e1", liquidity=None))
    comps = rank([c], profile=_profile()).ranked[0].ranking_components
    assert comps["liquidity_component"] == Decimal("0.80")      # unknown_default, ni 0 ni 1
    measured = _elig(_cand("m", "e2", liquidity=Decimal("0.50")))
    comps2 = rank([measured], profile=_profile()).ranked[0].ranking_components
    assert comps2["liquidity_component"] == Decimal("0.50")     # mesuré -> utilisé


def test_reliability_baseline_when_calibration_absent():
    none_cal = rank([_elig(_cand("n", "e1", calibration=None))], profile=_profile())
    assert none_cal.ranked[0].ranking_components["reliability_component"] == Decimal("0.60")  # baseline
    with_cal = rank([_elig(_cand("c", "e2", calibration=Decimal("0.92")))], profile=_profile())
    assert with_cal.ranked[0].ranking_components["reliability_component"] == Decimal("0.92")


def test_non_supported_eligible_is_non_rankable():
    # Défensif : un ELIGIBLE non SUPPORTED (ne devrait pas exister) -> rejet explicite.
    c = _elig(_cand("x", "e1", maturity="EXPERIMENTAL"))
    res = rank([c], profile=_profile())
    assert res.ranked == ()
    assert res.non_rankable[0].policy_reasons == (R.RANKING_MODEL_NOT_SUPPORTED,)


# ── Formule : policy_component retiré (D1) ────────────────────────────────────
def test_policy_component_absent_from_decomposition():
    comps = rank([_elig(_cand())], profile=_profile()).ranked[0].ranking_components
    assert "policy_component" not in comps
    assert set(comps) == {
        "value_component", "reliability_component", "quality_component",
        "freshness_component", "liquidity_component", "uncertainty_penalty",
        "concentration_penalty", "base_score", "ranking_score"}


# ── Neutralité cross-sport (§11/§12, DoD #7) ──────────────────────────────────
# Le score ne lit QUE le contrat économique normalisé (value/reliability/quality/
# freshness/liquidity/uncertainty). `sport`/`competition_id` sont portés par le
# candidat (identité/exposition/audit) mais ne doivent JAMAIS biaiser le classement :
# pas de bonus historique au football (§12). Candidats de test explicitement
# synthétiques — aucune sortie de modèle fabriquée.
def test_ranking_is_sport_neutral_identical_economics_identical_score():
    from dataclasses import replace
    from src.agents.quant.advisor.ranking.scorer import score_base
    profile = _profile()
    fb = _cand("c1")                                   # sport="football"
    tn = replace(fb, sport="tennis", competition_id="comp:atp")
    assert score_base(fb, profile).base_score == score_base(tn, profile).base_score


def test_ranking_gives_no_bonus_to_football():
    from dataclasses import replace
    fb = _cand("fb", "e1", ev_low=Decimal("0.04"))     # football, EV plus faible
    tn = replace(_cand("tn", "e2", ev_low=Decimal("0.12")),
                 sport="tennis", competition_id="comp:atp")   # autre sport, EV plus forte
    res = rank([_elig(fb), _elig(tn)], profile=_profile())
    assert _ranked_ids(res)[0] == "tn"                 # l'économie prime, jamais le sport
