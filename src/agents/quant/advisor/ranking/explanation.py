"""Décomposition explicable du score (PRD §12 « chaque composant est
explicable »). Assemble le `ranking_components` final (composants de base +
concentration + score) et porte la divulgation de la nature gloutonne V1."""

from __future__ import annotations

from decimal import Decimal

# Divulgation obligatoire (ADR-ADV-005 D5, ADV-NFR-012) : le classement est une
# heuristique séquentielle, JAMAIS un optimum global de portefeuille.
CONCENTRATION_HEURISTIC_NOTE = (
    "concentration_penalty séquentiel/glouton (dépend des candidats déjà "
    "retenus) : classement V1 par heuristique, jamais un optimum global"
)


def ranking_components(
    base_components: dict[str, Decimal], base_score: Decimal,
    concentration_penalty: Decimal, ranking_score: Decimal,
) -> dict[str, Decimal]:
    """Décomposition complète et déterministe attachée à un candidat classé."""
    return {
        **base_components,
        "concentration_penalty": concentration_penalty,
        "base_score": base_score,
        "ranking_score": ranking_score,
    }
