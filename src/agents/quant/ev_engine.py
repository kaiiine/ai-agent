"""Détection de value et décision de pari — EV, Kelly fractionné, combinés.

Aucun LLM ici : calculs déterministes uniquement. Décision au vocabulaire
du PRD axon-quant : BET (edge confirmé) / WATCH (edge incertain, à surveiller)
/ ABSTAIN (pas d'edge ou edge trop incertain).
"""

from __future__ import annotations

# Seuil provisoirement relevé à 6% : l'IC bootstrap du moteur ne capture que
# le bruit d'échantillonnage (pas l'erreur de spécification du modèle), donc
# la borne basse utilisée pour la décision est trop optimiste. À redescendre
# vers 4% une fois l'incertitude réelle calibrée au backtest.
EV_THRESHOLD = 0.06

# P(EV>0) minimale pour un BET. Valeur de départ prudente, pas une constante
# universelle : à recalibrer par domaine (championnat/marché) une fois backtesté.
P_EV_POSITIVE_THRESHOLD = 0.80

KELLY_FRACTION = 0.25     # quart de Kelly — non négociable (plein Kelly = ruine)


def implied_probability(odds: float) -> float:
    """Probabilité implicite d'une cote, marge du book incluse."""
    return 1 / odds


def no_vig_probabilities(odds: dict[str, float | None]) -> dict[str, float]:
    """Retire la marge du book (normalisation proportionnelle) sur un marché complet.

    `odds` : ex. {"home": 2.15, "draw": 3.4, "away": 3.2} — les valeurs absentes
    (ex. pas de nul en tennis) sont ignorées.
    """
    raw = {selection: 1 / value for selection, value in odds.items() if value}
    total = sum(raw.values())
    return {selection: round(value / total, 4) for selection, value in raw.items()}


def expected_value(model_prob: float, odds: float) -> float:
    """EV d'un pari : (proba_modèle × cote) - 1. Positif = value."""
    return model_prob * odds - 1


def probability_ev_positive(samples: list[float], odds: float) -> float:
    """Fraction des échantillons bootstrap pour lesquels l'EV serait positive."""
    positive_count = sum(1 for prob in samples if expected_value(prob, odds) > 0)
    return round(positive_count / len(samples), 4)


def conservative_ev(confidence_low: float, odds: float) -> float:
    """EV à la borne basse de l'intervalle de crédibilité à 90% — vue prudente de l'edge."""
    return round(expected_value(confidence_low, odds), 4)


def minimum_odds(model_prob: float) -> float:
    """Cote minimale pour que l'EV atteigne EV_THRESHOLD à cette probabilité."""
    return round((1 + EV_THRESHOLD) / model_prob, 3)


def kelly_stake(model_prob: float, odds: float, bankroll: float) -> float:
    """Mise recommandée en quart de Kelly. 0 si pas d'edge."""
    edge = model_prob * odds - 1
    if edge <= 0:
        return 0.0
    kelly = edge / (odds - 1)
    return round(bankroll * kelly * KELLY_FRACTION, 2)


def analyze_bet(
    model_prob: float,
    confidence_90: list[float],
    samples: list[float],
    odds: float,
    bankroll: float = 100.0,
) -> dict:
    """Analyse complète d'un pari simple : EV, incertitude bootstrap, décision.

    "BET" seulement si P(EV>0) ET la borne basse de l'EV dépassent toutes les
    deux leur seuil — un EV moyen positif seul ne suffit pas (edge peut-être
    réel mais trop incertain pour être joué).
    """
    ev = expected_value(model_prob, odds)
    p_positive = probability_ev_positive(samples, odds)
    ev_low = conservative_ev(confidence_90[0], odds)

    if ev <= 0:
        decision, reason = "ABSTAIN", "EV_NEGATIVE"
    elif p_positive >= P_EV_POSITIVE_THRESHOLD and ev_low >= EV_THRESHOLD:
        decision, reason = "BET", "EDGE_CONFIRMED"
    elif ev > EV_THRESHOLD:
        decision, reason = "WATCH", "EDGE_UNCERTAIN"
    else:
        decision, reason = "ABSTAIN", "EDGE_BELOW_THRESHOLD"

    return {
        "odds": odds,
        "implied_probability": round(implied_probability(odds), 4),
        "model_probability": round(model_prob, 4),
        "credible_interval_90": confidence_90,
        "raw_ev": round(ev, 4),
        "probability_ev_positive": p_positive,
        "conservative_ev": ev_low,
        "minimum_odds": minimum_odds(model_prob),
        "decision": decision,
        "reason_codes": [reason],
        "recommended_stake": kelly_stake(model_prob, odds, bankroll) if decision == "BET" else 0.0,
        "bankroll": bankroll,
    }


def analyze_parlay(legs: list[dict], bankroll: float = 100.0) -> dict:
    """Analyse d'un combiné multi-matchs.

    `legs` : [{"model_prob": float, "odds": float, "match_id": str}]

    Décision sur l'EV point (pas de P(EV>0) combiné : les échantillons bootstrap
    de matchs différents ne sont pas indépendants de façon fiable, les combiner
    donnerait une fausse précision). Deux legs sur le même match_id → corrélation,
    EV combiné non fiable (utiliser same_match_combo_analyze en amont).
    """
    if len(legs) < 2:
        raise ValueError("Un combiné doit avoir au moins 2 sélections")

    combined_odds = 1.0
    combined_prob = 1.0
    for leg in legs:
        combined_odds *= leg["odds"]
        combined_prob *= leg["model_prob"]

    match_ids = [leg.get("match_id", "") for leg in legs]
    correlated = len(match_ids) != len(set(match_ids))

    parlay_ev = expected_value(combined_prob, combined_odds)
    single_evs = [round(expected_value(leg["model_prob"], leg["odds"]), 4) for leg in legs]

    if correlated:
        decision, reason = "ABSTAIN", "CORRELATED_LEGS"
    elif parlay_ev > EV_THRESHOLD:
        decision, reason = "BET", "EDGE_CONFIRMED"
    elif parlay_ev > 0:
        decision, reason = "WATCH", "EDGE_UNCERTAIN"
    else:
        decision, reason = "ABSTAIN", "EV_NEGATIVE"

    return {
        "combined_odds": round(combined_odds, 2),
        "combined_probability": round(combined_prob, 4),
        "raw_ev": round(parlay_ev, 4),
        "single_leg_evs": single_evs,
        "sum_single_leg_evs": round(sum(single_evs), 4),
        "correlation_detected": correlated,
        "correlation_warning": (
            "Deux sélections sur le même match : utiliser same_match_combo_analyze "
            "qui calcule la probabilité jointe exacte depuis la matrice de scores."
        ) if correlated else None,
        "decision": decision,
        "reason_codes": [reason],
        "recommended_stake": kelly_stake(combined_prob, combined_odds, bankroll) if decision == "BET" else 0.0,
    }
