"""Codes de rejet/statut STABLES (PRD §11.4, ADR-ADV-004).

Chaînes stables et versionnées : elles sont exposées (CLI/API) et consommées par
`rejection_summary` ; elles ne doivent jamais changer silencieusement de valeur."""

from __future__ import annotations

# Maturité du modèle.
MODEL_NOT_SUPPORTED = "MODEL_NOT_SUPPORTED"
EXPERIMENTAL_REVIEW_ONLY = "EXPERIMENTAL_REVIEW_ONLY"
RANKING_MISSING_PROBABILITY = "RANKING_MISSING_PROBABILITY"

# Valeur / qualité / fraîcheur.
LOW_WORST_CASE_EV = "LOW_WORST_CASE_EV"
LOW_DATA_QUALITY = "LOW_DATA_QUALITY"
STALE_ODDS = "STALE_ODDS"              # fraîcheur MESURÉE et insuffisante
FRESHNESS_UNKNOWN = "FRESHNESS_UNKNOWN"  # fraîcheur NON mesurable (≠ STALE_ODDS)

# Filtres utilisateur.
USER_FILTERED_SPORT = "USER_FILTERED_SPORT"
USER_FILTERED_COMPETITION = "USER_FILTERED_COMPETITION"
USER_FILTERED_MARKET = "USER_FILTERED_MARKET"
USER_FILTERED_BOOKMAKER = "USER_FILTERED_BOOKMAKER"
USER_EXCLUDED_EVENT = "USER_EXCLUDED_EVENT"
USER_EXCLUDED_PARTICIPANT = "USER_EXCLUDED_PARTICIPANT"

# Validité / contraintes.
EVENT_ALREADY_STARTED = "EVENT_ALREADY_STARTED"
IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
STAKE_LIMIT_TOO_LOW = "STAKE_LIMIT_TOO_LOW"
BOOSTED_MARKET_NOT_SUPPORTED = "BOOSTED_MARKET_NOT_SUPPORTED"

# Ranking (Lot 5) : un ELIGIBLE sans input REQUIRED est rejeté au ranking, jamais
# rendu au hasard (gardes défensives — la Policy garantit déjà ces inputs).
RANKING_MISSING_FRESHNESS = "RANKING_MISSING_FRESHNESS"
RANKING_MODEL_NOT_SUPPORTED = "RANKING_MODEL_NOT_SUPPORTED"

# Corrélation intra-événement : deux sélections issues de la MÊME distribution
# ne sont pas deux expositions indépendantes. Le code est distinct d'un rejet de
# valeur — le candidat était bon, c'est sa DÉPENDANCE qui l'écarte, et un rapport
# doit pouvoir le dire.
CORRELATED_SAME_ORIGIN = "CORRELATED_SAME_ORIGIN"

# Combos (Lot 9) : code d'avertissement STABLE et machine-readable — un combo
# admissible existe mais n'a pas pu devenir une PortfolioLine faute de contrat de
# sizing COMBO. DISTINGUE ce cas d'un véritable NO_OPPORTUNITY (Lot 10 : replay).
COMBO_SIZING_NOT_AVAILABLE = "COMBO_SIZING_NOT_AVAILABLE"

ALL_REASON_CODES = frozenset({
    MODEL_NOT_SUPPORTED, EXPERIMENTAL_REVIEW_ONLY,
    LOW_WORST_CASE_EV, LOW_DATA_QUALITY, STALE_ODDS, FRESHNESS_UNKNOWN,
    USER_FILTERED_SPORT, USER_FILTERED_COMPETITION, USER_FILTERED_MARKET,
    USER_FILTERED_BOOKMAKER, USER_EXCLUDED_EVENT, USER_EXCLUDED_PARTICIPANT,
    EVENT_ALREADY_STARTED, IDENTITY_CONFLICT, STAKE_LIMIT_TOO_LOW,
    BOOSTED_MARKET_NOT_SUPPORTED,
    RANKING_MISSING_FRESHNESS, RANKING_MODEL_NOT_SUPPORTED,
    COMBO_SIZING_NOT_AVAILABLE,
})
