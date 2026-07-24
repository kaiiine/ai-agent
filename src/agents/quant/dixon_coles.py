"""Moteur Poisson-DC — Poisson pondéré par la forme, correction Dixon-Coles.

Nommage honnête : ce n'est PAS le Dixon-Coles complet du papier de 1997
(régression MLE conjointe sur toute la ligue). Les forces sont estimées sur la
forme récente de chaque équipe, avec les corrections suivantes :

- Normalisation par lieu : un but marqué à l'extérieur vaut plus qu'à domicile.
- Ajustement adversaire (optionnel) : un but contre le leader vaut plus qu'un
  but contre le dernier, via un proxy de force issu du classement.
- Shrinkage bayésien vers la moyenne de la ligue : avec n petit, l'estimation
  est tirée vers 1.0 — évite la sur-confiance sur 8 matchs.
- Correction tau de Dixon-Coles sur les scores faibles (0-0, 1-0, 0-1, 1-1).

Buts domicile ~ Poisson(lambda), buts extérieur ~ Poisson(mu) :
    lambda = LEAGUE_AVG_GOALS × HOME_ADVANTAGE × attaque_home × défense_away
    mu     = LEAGUE_AVG_GOALS × AWAY_FACTOR   × attaque_away × défense_home

Limites connues (à vérifier au backtest, bloquant avant mise réelle) :
- Le bootstrap mesure le bruit d'échantillonnage, pas l'erreur de
  spécification du modèle → l'IC réel est plus large que l'IC affiché.
- rho est fixé à la valeur du papier original par défaut ; à ré-estimer sur
  le championnat cible pendant le backtest.

Aucun LLM ici : calculs déterministes et testables uniquement.
"""

from __future__ import annotations
import math
import random

LEAGUE_AVG_GOALS = 1.35   # buts par équipe et par match (référence Europe)
HOME_ADVANTAGE = 1.11     # multiplicateur domicile → 1.35 × 1.11 ≈ 1.50
AWAY_FACTOR = 0.89        # multiplicateur extérieur → 1.35 × 0.89 ≈ 1.20

# Shrinkage bayésien : poids du prior ligue en équivalent-matchs.
# force = (n × estimé + K × 1.0) / (n + K)
# Valeur d'attente NON calibrée (choisie dans la fourchette usuelle 10-15) :
# hyperparamètre à balayer au backtest, comme rho. Trop petit → sur-confiance
# sur petits échantillons ; trop grand → écrase le signal des équipes atypiques.
DEFAULT_SHRINKAGE_K = 12

# Corrélation des scores faibles — papier Dixon-Coles 1997 (foot anglais).
# Valeur par défaut uniquement : à ré-estimer au backtest par championnat.
DEFAULT_RHO = -0.13

# Pondération exponentielle : le match le plus récent pèse ~2.5x le 10e
DECAY = 0.10

MAX_GOALS = 10
BOOTSTRAP_ITER = 500

# Bornes de sécurité sur les forces estimées
STRENGTH_MIN = 0.25
STRENGTH_MAX = 3.0


def team_strengths(
    form: list[dict],
    opponent_ratings: dict | None = None,
    shrinkage_k: float = DEFAULT_SHRINKAGE_K,
) -> dict:
    """Force d'attaque et de défense d'une équipe depuis sa forme récente.

    `form` vient de gateway.recent_form() — du plus récent au plus ancien.
    `opponent_ratings` : dict {opponent_id: force} (1.0 = moyen, >1 = fort),
    typiquement issu de standings_strength(). Si fourni, un but marqué contre
    un adversaire fort compte plus, un but encaissé contre un fort compte moins.

    attack > 1 : marque plus que la moyenne ; defense > 1 : encaisse plus (mauvais).
    Les estimations sont shrinkées vers 1.0 selon la taille d'échantillon.
    """
    if not form:
        raise ValueError("Forme vide — impossible d'estimer les forces")

    attack_sum = 0.0
    defense_sum = 0.0
    total_weight = 0.0

    for i, match in enumerate(form):  # i=0 → le plus récent
        weight = math.exp(-DECAY * i)
        is_home = match["is_home"]
        scored = match["goals_home"] if is_home else match["goals_away"]
        conceded = match["goals_away"] if is_home else match["goals_home"]

        # Normalisation par lieu : à domicile on attend plus de buts
        expected_scored = LEAGUE_AVG_GOALS * (HOME_ADVANTAGE if is_home else AWAY_FACTOR)
        expected_conceded = LEAGUE_AVG_GOALS * (AWAY_FACTOR if is_home else HOME_ADVANTAGE)

        # Ajustement adversaire (proxy classement) : marquer contre un fort
        # vaut plus, encaisser contre un fort est moins grave
        opp_rating = 1.0
        if opponent_ratings:
            opp_rating = opponent_ratings.get(match.get("opponent_id"), 1.0)

        attack_sum += weight * (scored / expected_scored) * opp_rating
        defense_sum += weight * (conceded / expected_conceded) / opp_rating
        total_weight += weight

    attack_raw = attack_sum / total_weight
    defense_raw = defense_sum / total_weight

    # Shrinkage vers la moyenne ligue (1.0), pondéré par l'échantillon effectif
    n_eff = total_weight
    attack = (n_eff * attack_raw + shrinkage_k * 1.0) / (n_eff + shrinkage_k)
    defense = (n_eff * defense_raw + shrinkage_k * 1.0) / (n_eff + shrinkage_k)

    attack = min(max(attack, STRENGTH_MIN), STRENGTH_MAX)
    defense = min(max(defense, STRENGTH_MIN), STRENGTH_MAX)
    return {"attack": round(attack, 4), "defense": round(defense, 4)}


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Correction Dixon-Coles des scores faibles."""
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def score_matrix(
    home_strengths: dict,
    away_strengths: dict,
    rho: float = DEFAULT_RHO,
) -> list[list[float]]:
    """Matrice P(score = x-y) pour x, y de 0 à MAX_GOALS. Somme normalisée à 1.

    L'avantage du terrain est appliqué ici, explicitement, au match cible —
    pas dilué dans l'estimation de forme.
    """
    lam = LEAGUE_AVG_GOALS * HOME_ADVANTAGE * home_strengths["attack"] * away_strengths["defense"]
    mu = LEAGUE_AVG_GOALS * AWAY_FACTOR * away_strengths["attack"] * home_strengths["defense"]

    matrix = [
        [
            _tau(x, y, lam, mu, rho) * _poisson_pmf(x, lam) * _poisson_pmf(y, mu)
            for y in range(MAX_GOALS + 1)
        ]
        for x in range(MAX_GOALS + 1)
    ]

    total = sum(sum(row) for row in matrix)
    return [[p / total for p in row] for row in matrix]


# ── Marchés ────────────────────────────────────────────────────────────────────

def _market_predicate(market: str):
    """Retourne le prédicat (x, y) -> bool d'un marché nommé.

    Marchés supportés : home, draw, away, over_X_Y, under_X_Y, btts_yes, btts_no.
    Exemple : "over_2_5" → x + y > 2.5
    """
    if market == "home":
        return lambda x, y: x > y
    if market == "draw":
        return lambda x, y: x == y
    if market == "away":
        return lambda x, y: x < y
    if market == "btts_yes":
        return lambda x, y: x >= 1 and y >= 1
    if market == "btts_no":
        return lambda x, y: x == 0 or y == 0
    for prefix, over in (("over_", True), ("under_", False)):
        if market.startswith(prefix):
            try:
                line = float(market[len(prefix):].replace("_", "."))
            except ValueError:
                break
            if over:
                return lambda x, y: x + y > line
            return lambda x, y: x + y < line
    raise ValueError(f"Marché inconnu : {market}")


def joint_probability(matrix: list[list[float]], markets: list[str]) -> float:
    """Probabilité jointe EXACTE de plusieurs marchés du même match.

    Somme les cellules de la matrice qui satisfont TOUS les marchés à la fois.
    C'est le calcul correct pour un combiné intra-match — le produit des probas
    marginales est faux dès que les événements sont corrélés.
    """
    predicates = [_market_predicate(m) for m in markets]
    return sum(
        p
        for x, row in enumerate(matrix)
        for y, p in enumerate(row)
        if all(pred(x, y) for pred in predicates)
    )


def market_probabilities(matrix: list[list[float]]) -> dict:
    """Dérive tous les marchés standards depuis la matrice de scores."""
    home = draw = away = 0.0
    btts = 0.0
    totals: dict[float, float] = {1.5: 0.0, 2.5: 0.0, 3.5: 0.0}
    scores: list[tuple[str, float]] = []

    for x, row in enumerate(matrix):
        for y, p in enumerate(row):
            if x > y:
                home += p
            elif x == y:
                draw += p
            else:
                away += p
            if x >= 1 and y >= 1:
                btts += p
            for line in totals:
                if x + y > line:
                    totals[line] += p
            scores.append((f"{x}-{y}", p))

    scores.sort(key=lambda s: s[1], reverse=True)

    return {
        "home": round(home, 4),
        "draw": round(draw, 4),
        "away": round(away, 4),
        "over_1_5": round(totals[1.5], 4),
        "under_1_5": round(1 - totals[1.5], 4),
        "over_2_5": round(totals[2.5], 4),
        "under_2_5": round(1 - totals[2.5], 4),
        "over_3_5": round(totals[3.5], 4),
        "under_3_5": round(1 - totals[3.5], 4),
        "btts_yes": round(btts, 4),
        "btts_no": round(1 - btts, 4),
        "top_scores": [{"score": s, "prob": round(p, 4)} for s, p in scores[:5]],
    }


# ── Pipeline complet ───────────────────────────────────────────────────────────

def _bootstrap_samples(
    home_form: list[dict],
    away_form: list[dict],
    opponent_ratings: dict | None,
    compute,  # (home_strengths, away_strengths) -> dict[str, float]
    tracked: list[str],
) -> dict[str, list[float]]:
    """Ré-échantillonne la forme BOOTSTRAP_ITER fois, calcule `compute` à chaque tirage."""
    samples: dict[str, list[float]] = {key: [] for key in tracked}
    rng = random.Random(42)  # reproductible

    for _ in range(BOOTSTRAP_ITER):
        h_sample = rng.choices(home_form, k=len(home_form))
        a_sample = rng.choices(away_form, k=len(away_form))
        values = compute(
            team_strengths(h_sample, opponent_ratings),
            team_strengths(a_sample, opponent_ratings),
        )
        for key in tracked:
            samples[key].append(values[key])
    return samples


def _confidence_interval(values: list[float]) -> list[float]:
    """Intervalle à 90% (percentiles 5/95) à partir d'échantillons bootstrap."""
    ordered = sorted(values)
    lo = ordered[int(0.05 * len(ordered))]
    hi = ordered[int(0.95 * len(ordered))]
    return [round(lo, 4), round(hi, 4)]


def dixon_coles_probabilities(
    home_form: list[dict],
    away_form: list[dict],
    opponent_ratings: dict | None = None,
    rho: float = DEFAULT_RHO,
) -> dict:
    """Pipeline complet : forces → matrice → marchés + IC 90% bootstrap.

    Note honnêteté : l'IC bootstrap capture le bruit d'échantillonnage de la
    forme, pas l'erreur de spécification du modèle. L'incertitude réelle est
    plus large que l'intervalle affiché.
    """
    if not home_form or not away_form:
        raise ValueError("Forme insuffisante pour calculer une probabilité")

    home_str = team_strengths(home_form, opponent_ratings)
    away_str = team_strengths(away_form, opponent_ratings)
    point = market_probabilities(score_matrix(home_str, away_str, rho))

    tracked = ["home", "draw", "away", "over_2_5", "btts_yes"]
    samples = _bootstrap_samples(
        home_form, away_form, opponent_ratings,
        lambda h, a: market_probabilities(score_matrix(h, a, rho)),
        tracked,
    )
    confidence = {key: _confidence_interval(values) for key, values in samples.items()}

    return {
        "probabilities": point,
        "confidence_90": confidence,
        "strengths": {"home": home_str, "away": away_str},
        "sample_size": {"home": len(home_form), "away": len(away_form)},
        "opponent_adjustment": opponent_ratings is not None,
        # Le classement source est celui d'AUJOURD'HUI (pas de l'époque des
        # matchs de forme) — voir gateway.standings_strength.
        "standings_snapshot": "current" if opponent_ratings is not None else None,
        "rho": rho,
    }


def market_probability(
    home_form: list[dict],
    away_form: list[dict],
    market: str,
    opponent_ratings: dict | None = None,
    rho: float = DEFAULT_RHO,
) -> dict:
    """Probabilité d'un marché unique (n'importe lequel, cf. _market_predicate), avec bootstrap.

    Utilisé par ev_analyze : le tool ne reçoit jamais une probabilité toute faite,
    il donne équipes + marché et le calcul se fait entièrement ici.
    """
    home_str = team_strengths(home_form, opponent_ratings)
    away_str = team_strengths(away_form, opponent_ratings)
    matrix = score_matrix(home_str, away_str, rho)
    point = joint_probability(matrix, [market])

    samples = _bootstrap_samples(
        home_form, away_form, opponent_ratings,
        lambda h, a: {"p": joint_probability(score_matrix(h, a, rho), [market])},
        ["p"],
    )["p"]

    return {
        "probability": round(point, 4),
        "confidence_90": _confidence_interval(samples),
        "samples": samples,
    }


def same_match_combo(
    home_form: list[dict],
    away_form: list[dict],
    markets: list[str],
    opponent_ratings: dict | None = None,
    rho: float = DEFAULT_RHO,
) -> dict:
    """Probabilité jointe exacte d'un combiné intra-match, avec IC 90%.

    Compare aussi au produit naïf des marginales pour montrer l'effet de la
    corrélation (positif = les événements se renforcent, négatif = s'opposent).
    """
    if len(markets) < 2:
        raise ValueError("Un combiné intra-match doit avoir au moins 2 marchés")

    home_str = team_strengths(home_form, opponent_ratings)
    away_str = team_strengths(away_form, opponent_ratings)
    matrix = score_matrix(home_str, away_str, rho)

    joint = joint_probability(matrix, markets)
    naive = 1.0
    for market in markets:
        naive *= joint_probability(matrix, [market])

    samples = _bootstrap_samples(
        home_form, away_form, opponent_ratings,
        lambda h, a: {"joint": joint_probability(score_matrix(h, a, rho), markets)},
        ["joint"],
    )["joint"]

    return {
        "markets": markets,
        "joint_probability": round(joint, 4),
        "confidence_90": _confidence_interval(samples),
        "samples": samples,
        "naive_product": round(naive, 4),
        "correlation_effect": round(joint - naive, 4),
        "sample_size": {"home": len(home_form), "away": len(away_form)},
    }
