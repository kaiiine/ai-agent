"""Moteur de probabilités — Elo dynamique (MVP, migration Dixon-Coles prévue).

Aucun LLM ici : calculs déterministes et testables uniquement.
"""

from __future__ import annotations
import math
import random

BASE_RATING = 1500
K_FACTOR = 32
HOME_ADVANTAGE = 65   # bonus Elo standard du terrain (~0.09 de proba)
DRAW_BASE = 0.26      # taux de nul empirique en foot quand les équipes sont proches
BOOTSTRAP_ITER = 500


def build_rating(form: list[dict]) -> float:
    """Calcule le rating Elo d'une équipe depuis ses derniers matchs.

    `form` vient de gateway.recent_form() — du plus récent au plus ancien.
    Les matchs récents pèsent plus (pondération exponentielle décroissante).
    """
    rating = BASE_RATING
    # Du plus ancien au plus récent pour que les récents aient le dernier mot
    for i, match in enumerate(reversed(form)):
        team_goals = match["goals_home"] if match["is_home"] else match["goals_away"]
        opp_goals = match["goals_away"] if match["is_home"] else match["goals_home"]

        actual = 1.0 if team_goals > opp_goals else 0.0 if team_goals < opp_goals else 0.5
        expected = 0.5  # adversaire inconnu → supposé au niveau de base

        # marge de victoire : un 4-0 pèse plus qu'un 1-0
        margin = abs(team_goals - opp_goals)
        margin_mult = math.log(margin + 1) + 1

        # les matchs récents comptent plus (le dernier ~2x plus que le 10e)
        recency = 0.5 + 0.5 * (i + 1) / len(form)

        rating += K_FACTOR * margin_mult * recency * (actual - expected)
    return rating


def match_probabilities(home_rating: float, away_rating: float) -> dict:
    """Probabilités 1N2 depuis les ratings Elo.

    Retourne {"home": p1, "draw": pN, "away": p2} — somme = 1.
    """
    diff = home_rating + HOME_ADVANTAGE - away_rating
    # Proba de victoire hors nul (formule Elo classique)
    home_no_draw = 1 / (1 + 10 ** (-diff / 400))

    # Le nul est plus probable quand les équipes sont proches
    closeness = 1 - abs(2 * home_no_draw - 1)
    draw = DRAW_BASE * (0.5 + 0.5 * closeness)

    home = home_no_draw * (1 - draw)
    away = (1 - home_no_draw) * (1 - draw)
    return {"home": round(home, 4), "draw": round(draw, 4), "away": round(away, 4)}


def probabilities_with_confidence(
    home_form: list[dict],
    away_form: list[dict],
) -> dict:
    """Probas 1N2 + intervalle de confiance à 90% par bootstrap.

    Rééchantillonne les matchs de forme pour mesurer la sensibilité du modèle
    à l'historique disponible. Peu de matchs → intervalle large → honnêteté.

    Retourne :
    {
      "probabilities": {"home", "draw", "away"},
      "confidence_90": {"home": [lo, hi], "draw": [lo, hi], "away": [lo, hi]},
      "sample_size": {"home": n, "away": n},
    }
    """
    if not home_form or not away_form:
        raise ValueError("Forme insuffisante pour calculer une probabilité")

    point = match_probabilities(build_rating(home_form), build_rating(away_form))

    samples: dict[str, list[float]] = {"home": [], "draw": [], "away": []}
    rng = random.Random(42)  # reproductible
    for _ in range(BOOTSTRAP_ITER):
        h_sample = rng.choices(home_form, k=len(home_form))
        a_sample = rng.choices(away_form, k=len(away_form))
        probs = match_probabilities(build_rating(h_sample), build_rating(a_sample))
        for key in samples:
            samples[key].append(probs[key])

    confidence = {}
    for key, values in samples.items():
        values.sort()
        lo = values[int(0.05 * len(values))]
        hi = values[int(0.95 * len(values))]
        confidence[key] = [round(lo, 4), round(hi, 4)]

    return {
        "probabilities": point,
        "confidence_90": confidence,
        "sample_size": {"home": len(home_form), "away": len(away_form)},
    }
