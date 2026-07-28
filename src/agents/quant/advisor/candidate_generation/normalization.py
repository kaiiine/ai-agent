"""Champs dérivés AUTORISÉS du Candidate Generator (PRD §10.2) + identifiant
stable (ADR-ADV-003).

Arithmétique Decimal EXACTE (soustraction/produit) : aucun arrondi. Seule
`fair_odds = 1/fair_probability` implique une division ; elle est calculée à une
précision de CALCUL fixe et déterministe (défaut Decimal, 28 chiffres
significatifs) — ce n'est PAS une politique d'arrondi métier (mise/affichage),
laquelle est reportée à ADR-ADV-002 / Lot 8.

Aucune donnée sportive nouvelle n'est créée : `fair_probability`,
`probability_low`, `bookmaker_odds`, `implied_probability` proviennent déjà,
validées, de l'évaluation adaptée."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Context, Decimal

from ..domain.money import ONE, ZERO

# Précision de CALCUL déterministe pour la seule division (fair_odds).
# Indépendante du contexte Decimal ambiant. Pas un arrondi métier (ADR-ADV-002).
_ODDS_DIVISION = Context(prec=28)


def fair_odds_from_probability(fair_probability: Decimal) -> Decimal:
    """`fair_odds = 1 / fair_probability`. Exige `fair_probability > 0`
    (probabilité nulle -> cote indéfinie : refus explicite, jamais d'infini
    silencieux)."""
    if fair_probability <= ZERO:
        raise ValueError(
            f"fair_probability doit être > 0 pour dériver fair_odds, reçu {fair_probability}")
    return _ODDS_DIVISION.divide(ONE, fair_probability)


def edge(probability: Decimal, no_vig_probability: Decimal) -> Decimal:
    """Edge = probabilité modèle − probabilité no-vig du marché.

    Définition CANONIQUE alignée sur le Betting Engine (`decision.py` :
    `edge = model_p − no_vig_p`), pas une sémantique nouvelle : le no-vig (marge
    du bookmaker retirée) est le seuil de rentabilité de référence. `no_vig` est
    propagé du moteur, jamais recalculé ici."""
    return probability - no_vig_probability


def expected_value(probability: Decimal, bookmaker_odds: Decimal) -> Decimal:
    """EV = probabilité × cote − 1 (même formule que le moteur : `ev`)."""
    return probability * bookmaker_odds - ONE


def stable_candidate_id(
    *, bookmaker: str, event_id: str, market_id: str, selection: str,
    model_version: str, observed_at: datetime,
) -> str:
    """Identifiant STABLE d'une OFFRE observée (ADR-ADV-003).

    Champs du hash : bookmaker, event_id, market_id, selection, model_version, et
    `observed_at` — l'instant d'OBSERVATION des cotes côté bookmaker
    (= RawBookmakerEvent.fetched_at), PAS le `decision_time` de la requête
    Advisor. Deux requêtes Advisor différentes qui observent le même snapshot
    (même `observed_at`) produisent donc le MÊME candidate_id.

    Limite V1 documentée : `fetched_at` est l'instant de SCAN, faute d'un
    timestamp de mise à jour de cote intrinsèque Winamax ou d'un snapshot_id
    stable (non capturés par le connecteur — dette, même famille que Q5). Deux
    scans distincts de cotes inchangées produisent aujourd'hui des ids distincts."""
    payload = "|".join((bookmaker, event_id, market_id, selection,
                        model_version, observed_at.isoformat()))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"cand:{digest}"
