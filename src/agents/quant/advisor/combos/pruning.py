"""Génération canonique des paires (top-K) + ranking déterministe des combos
admissibles (Lot 9). Chaque paire est générée AU PLUS une fois ; (A,B) et (B,A)
sont le même combo. Aucune modification silencieuse d'identité."""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.candidates import CandidateEvaluation
from ..domain.money import ZERO


def canonical_pairs(top_k: Sequence[CandidateEvaluation]):
    """Paires non ordonnées (i<j) parmi les top-K, chacune une seule fois."""
    for i in range(len(top_k)):
        for j in range(i + 1, len(top_k)):
            yield top_k[i], top_k[j]


def _rank_key(combo):
    # Ordre total (current-state §10.6) : worst_case_ev desc, expected_value desc,
    # target_odds_match (True avant False), qualité MIN des legs desc, tuple lexical.
    return (
        -combo.pricing.worst_case_ev,
        -combo.pricing.expected_value,
        0 if combo.target_odds_match else 1,
        -(combo.min_leg_quality if combo.min_leg_quality is not None else ZERO),
        tuple(sorted(leg.candidate.candidate_id for leg in combo.legs)),
    )


def rank_combos(admissible):
    """Classement strictement reproductible, indépendant de l'ordre d'entrée
    (tie-break final = tuple lexical des candidate_id)."""
    return tuple(sorted(admissible, key=_rank_key))
