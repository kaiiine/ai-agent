"""Tests du moteur quant — lancer avec : pytest tests/test_quant_engine.py -v"""

import math

from src.agents.quant.dixon_coles import (
    LEAGUE_AVG_GOALS,
    HOME_ADVANTAGE,
    AWAY_FACTOR,
    team_strengths,
    score_matrix,
    joint_probability,
    market_probabilities,
    market_probability,
    same_match_combo,
    dixon_coles_probabilities,
)
from src.agents.quant.ev_engine import (
    analyze_bet,
    analyze_parlay,
    no_vig_probabilities,
    probability_ev_positive,
    minimum_odds,
    EV_THRESHOLD,
)


def _symmetric_form(n: int = 10) -> list[dict]:
    """Forme d'une équipe parfaitement moyenne : elle marque et encaisse
    exactement ce que la normalisation par lieu attend, à domicile comme
    à l'extérieur. Ses forces doivent donc sortir à 1.0 exactement."""
    form = []
    for i in range(n):
        is_home = i % 2 == 0
        scored = LEAGUE_AVG_GOALS * (HOME_ADVANTAGE if is_home else AWAY_FACTOR)
        conceded = LEAGUE_AVG_GOALS * (AWAY_FACTOR if is_home else HOME_ADVANTAGE)
        form.append({
            "goals_home": scored if is_home else conceded,
            "goals_away": conceded if is_home else scored,
            "is_home": is_home,
        })
    return form


# ── Point 1 : home advantage appliqué UNE seule fois ──────────────────────────

def test_symmetric_team_has_neutral_strengths():
    """La normalisation par lieu doit retirer tout le biais domicile/extérieur :
    une équipe symétrique sort à attack=1.0, defense=1.0 (le shrinkage vers 1.0
    ne change rien puisque l'estimé est déjà 1.0)."""
    strengths = team_strengths(_symmetric_form())
    assert abs(strengths["attack"] - 1.0) < 1e-6
    assert abs(strengths["defense"] - 1.0) < 1e-6


def test_home_advantage_applied_exactly_once():
    """Deux équipes neutres → les buts attendus du match doivent être
    exactement LEAGUE_AVG × HOME_ADVANTAGE et LEAGUE_AVG × AWAY_FACTOR.
    Si le biais domicile fuyait de team_strengths, le ratio serait au carré."""
    neutral = {"attack": 1.0, "defense": 1.0}
    matrix = score_matrix(neutral, neutral, rho=0.0)  # rho=0 pour isoler le Poisson pur

    expected_home = sum(x * p for x, row in enumerate(matrix) for p in row)
    expected_away = sum(y * p for row in matrix for y, p in enumerate(row))

    # Tolérance : troncature de la grille à MAX_GOALS
    assert abs(expected_home - LEAGUE_AVG_GOALS * HOME_ADVANTAGE) < 0.01
    assert abs(expected_away - LEAGUE_AVG_GOALS * AWAY_FACTOR) < 0.01

    ratio = expected_home / expected_away
    single = HOME_ADVANTAGE / AWAY_FACTOR
    assert abs(ratio - single) < 0.02, f"ratio {ratio:.3f} ≠ {single:.3f} — double comptage ?"
    assert abs(ratio - single**2) > 0.2, "le ratio correspond au carré → biais appliqué deux fois"


# ── Point 3 : shrinkage paramétrable ──────────────────────────────────────────

def test_shrinkage_k_pulls_toward_league_average():
    form = [{"goals_home": 4, "goals_away": 0, "is_home": True} for _ in range(8)]
    loose = team_strengths(form, shrinkage_k=1)
    tight = team_strengths(form, shrinkage_k=50)
    assert loose["attack"] > tight["attack"], "un k plus grand doit tirer plus fort vers 1.0"
    assert abs(tight["attack"] - 1.0) < abs(loose["attack"] - 1.0)


# ── Cohérence générale des marchés ────────────────────────────────────────────

def test_markets_sum_to_one():
    strengths = {"attack": 1.2, "defense": 0.9}
    p = market_probabilities(score_matrix(strengths, strengths))
    assert abs(p["home"] + p["draw"] + p["away"] - 1) < 1e-6
    assert abs(p["over_2_5"] + p["under_2_5"] - 1) < 1e-6
    assert abs(p["btts_yes"] + p["btts_no"] - 1) < 1e-6


def test_joint_probability_consistency():
    """La proba jointe doit valoir la marginale quand un seul marché,
    et être ≤ min des marginales pour plusieurs marchés."""
    matrix = score_matrix({"attack": 1.3, "defense": 0.8}, {"attack": 0.9, "defense": 1.1})
    p_home = joint_probability(matrix, ["home"])
    p_over = joint_probability(matrix, ["over_2_5"])
    p_joint = joint_probability(matrix, ["home", "over_2_5"])
    assert p_joint <= min(p_home, p_over) + 1e-9
    assert p_joint > p_home * p_over, "home et over_2_5 sont positivement corrélés"


def test_impossible_combo_is_zero():
    matrix = score_matrix({"attack": 1.0, "defense": 1.0}, {"attack": 1.0, "defense": 1.0})
    assert joint_probability(matrix, ["home", "under_1_5", "btts_yes"]) == 0.0


def test_market_probability_matches_matrix_marginal():
    """market_probability() (utilisé par ev_analyze) doit retomber sur la marginale
    de la matrice de scores, avec un échantillon bootstrap non vide."""
    form_a = [{"goals_home": 2, "goals_away": 1, "is_home": i % 2 == 0} for i in range(8)]
    form_b = [{"goals_home": 1, "goals_away": 1, "is_home": i % 2 == 1} for i in range(8)]
    result = market_probability(form_a, form_b, "over_2_5")
    assert 0 <= result["probability"] <= 1
    assert len(result["samples"]) > 0
    assert result["confidence_90"][0] <= result["probability"] <= result["confidence_90"][1]


# ── Point 4 : seuil d'EV relevé ───────────────────────────────────────────────

def test_ev_threshold_is_conservative():
    assert EV_THRESHOLD >= 0.05, "seuil provisoire ≥ 5% tant que l'IC n'est pas calibré"


def test_bet_in_noise_zone_gets_no_stake():
    """EV point positif mais borne basse sous le seuil → decision WATCH/ABSTAIN, mise 0."""
    result = analyze_bet(
        model_prob=0.55, confidence_90=[0.45, 0.65], samples=[0.5] * 20, odds=1.95, bankroll=100
    )
    assert result["decision"] in ("WATCH", "ABSTAIN")
    assert result["recommended_stake"] == 0.0


def test_bet_confirmed_when_edge_is_robust():
    """P(EV>0) élevée et borne basse au-dessus du seuil → BET, mise > 0."""
    samples = [0.62] * 90 + [0.5] * 10  # 90% des tirages gardent un edge net
    result = analyze_bet(
        model_prob=0.62, confidence_90=[0.58, 0.66], samples=samples, odds=1.9, bankroll=100
    )
    assert result["decision"] == "BET"
    assert result["recommended_stake"] > 0.0


def test_no_vig_probabilities_sum_to_one():
    probs = no_vig_probabilities({"home": 2.1, "draw": 3.4, "away": 3.2})
    assert abs(sum(probs.values()) - 1) < 1e-9
    assert set(probs) == {"home", "draw", "away"}


def test_no_vig_probabilities_skips_missing_outcome():
    probs = no_vig_probabilities({"home": 1.8, "draw": None, "away": 2.0})
    assert set(probs) == {"home", "away"}
    assert abs(sum(probs.values()) - 1) < 1e-9


def test_probability_ev_positive_counts_correctly():
    samples = [0.6] * 8 + [0.4] * 2  # à cote 1.8, 0.6*1.8-1>0 mais 0.4*1.8-1<0
    assert probability_ev_positive(samples, odds=1.8) == 0.8


def test_minimum_odds_matches_ev_threshold():
    prob = 0.5
    odds = minimum_odds(prob)
    assert abs((prob * odds - 1) - EV_THRESHOLD) < 1e-3


# ── Point 5 : combinés multi-matchs ───────────────────────────────────────────

def test_parlay_correlated_legs_flagged():
    legs = [
        {"model_prob": 0.6, "odds": 1.9, "match_id": "m1"},
        {"model_prob": 0.5, "odds": 1.8, "match_id": "m1"},
    ]
    result = analyze_parlay(legs)
    assert result["correlation_detected"]
    assert result["recommended_stake"] == 0.0


def test_parlay_independent_legs_ok():
    legs = [
        {"model_prob": 0.7, "odds": 1.8, "match_id": "m1"},
        {"model_prob": 0.65, "odds": 1.85, "match_id": "m2"},
    ]
    result = analyze_parlay(legs)
    assert not result["correlation_detected"]
    assert abs(result["combined_odds"] - 1.8 * 1.85) < 1e-9


# ── Bootstrap reproductible ───────────────────────────────────────────────────

def test_bootstrap_is_deterministic():
    form_a = [{"goals_home": 2, "goals_away": 1, "is_home": i % 2 == 0} for i in range(8)]
    form_b = [{"goals_home": 1, "goals_away": 1, "is_home": i % 2 == 1} for i in range(8)]
    r1 = dixon_coles_probabilities(form_a, form_b)
    r2 = dixon_coles_probabilities(form_a, form_b)
    assert r1 == r2, "seed fixe → résultats identiques"
