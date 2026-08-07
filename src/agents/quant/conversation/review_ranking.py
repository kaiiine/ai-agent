"""Classement des candidats de REVUE — strictement séparé du classement argent.

`Advisor.rank()` ne classe que les `ELIGIBLE` : c'est voulu, le classement money
décide de l'allocation. Les `REVIEW_ONLY` en sortaient donc dans l'ordre où le
générateur les avait produits, c'est-à-dire aucun. Sur trente candidats, la
shortlist montrait les trois premiers arrivés.

Ce module classe les REVIEW_ONLY, et eux seuls. Il ne produit aucune mise, aucun
score de portefeuille, et n'entre jamais dans l'allocation — mélanger les deux
classements ferait entrer un candidat non misable dans une décision d'argent.

Deux règles de lecture, énoncées parce qu'elles sont contestables si on les tait :

- l'ordre suit `edge_low` puis `expected_value_low`, c'est-à-dire les bornes
  BASSES. Trier sur les valeurs moyennes remonterait les candidats dont
  l'incertitude est la plus large, ce qui est l'inverse de ce qu'on veut montrer ;
- l'ordre ne mesure pas une distance au misable. Aucun REVIEW_ONLY ne l'est, et
  le premier ne l'est pas moins que le dernier.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence


@dataclass(frozen=True)
class ReviewLine:
    """Une ligne de shortlist. Aucun champ de mise, par construction."""

    evaluation: Any
    rang: int

    @property
    def candidate(self) -> Any:
        return self.evaluation.candidate


def _cle(evaluation: Any) -> tuple:
    c = evaluation.candidate
    return (
        -(c.edge_low if c.edge_low is not None else Decimal("-1")),
        -(c.expected_value_low if c.expected_value_low is not None else Decimal("-1")),
        c.candidate_id,          # départage TOTAL : deux runs rendent le même ordre
    )


def rank_review(
    evaluations: Sequence[Any], *, une_par_evenement: bool = True,
) -> tuple[ReviewLine, ...]:
    """Classe les candidats de revue, au plus un par rencontre.

    Un marché 2-way produit deux sélections opposées pour le même match : si
    l'une a un edge positif, l'autre l'a mécaniquement négatif. Les afficher
    toutes deux remplissait la moitié de la shortlist avec le côté que le modèle
    juge justement mauvais.
    """
    ordonnes = sorted(evaluations, key=_cle)

    if une_par_evenement:
        vus: set[str] = set()
        retenus = []
        for evaluation in ordonnes:
            event_id = evaluation.candidate.event_id
            if event_id in vus:
                continue
            vus.add(event_id)
            retenus.append(evaluation)
        ordonnes = retenus

    return tuple(ReviewLine(evaluation=e, rang=i)
                 for i, e in enumerate(ordonnes, start=1))
