"""Invariant de performance : 1 événement -> 1 distribution -> N projections.

La faute naturelle, en généralisant, est de traiter chaque marché comme un
problème indépendant : N marchés, N constructions de features, N modèles
complets. Le coût explose avec le catalogue — 253 marchés sur un seul match
observé — et, bien plus grave, rien ne garantit plus que les N distributions
soient la MÊME : deux appels séparés peuvent diverger dès qu'un paramètre bouge.

Ces tests comptent les appels plutôt que les millisecondes. Un chronomètre
mesure la machine ; un compteur mesure l'algorithme, et c'est lui qui doit être
sous contrôle.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.sports.football.market_models.derived import (
    FootballDerivedPricer,
    double_chance,
    draw_no_bet,
    exact_score,
    issues_1x2,
    totals,
)
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel


class _Participant:
    def __init__(self, role, cid):
        self.role, self.canonical_id = role, cid


class _Event:
    event_id = "event:football:perf"
    participants = (_Participant("home", "team:h"), _Participant("away", "team:a"))


class _Features:
    def __init__(self):
        self.participant_features = {
            "team:h": {"attack_strength": 1.2, "defense_strength": 0.9},
            "team:a": {"attack_strength": 0.95, "defense_strength": 1.1}}
        self.missing_features = set()
        self.as_of = datetime(2026, 8, 1, tzinfo=timezone.utc)


class _ModeleCompteur(OneXTwoModel):
    """Compte les constructions de distribution — l'opération coûteuse."""

    def __init__(self):
        super().__init__()
        self.appels = 0

    def distribution(self, event, features, point_in_time):
        self.appels += 1
        return super().distribution(event, features, point_in_time)


def _contexte(features=None):
    return {"features": features or _Features(),
            "point_in_time": datetime(2026, 8, 2, tzinfo=timezone.utc)}


#: Les marchés d'un même événement, tels que l'inventaire les produit.
MARCHES = [
    (MarketFamily.MATCH_WINNER, {}),
    (MarketFamily.DOUBLE_CHANCE, {"source_family_id": 3072}),
    (MarketFamily.DRAW_NO_BET, {"source_family_id": 3535}),
    *[(MarketFamily.TOTALS, {"line": l, "source_family_id": 2749})
      for l in (1.5, 2.5, 3.5, 4.5, 5.5)],
]


def test_les_projections_d_un_evenement_sortent_d_une_seule_distribution():
    """L'invariant, compté : N marchés d'un même match, N projections, mais UNE
    distribution — celle du modèle, calculée une fois et lue N fois."""
    modele = _ModeleCompteur()
    contexte = _contexte()
    matrix = modele.distribution(_Event(), contexte["features"], contexte["point_in_time"])
    base = modele.appels

    projections = {
        "MATCH_WINNER": issues_1x2(matrix),
        "DOUBLE_CHANCE": double_chance(matrix),
        "DRAW_NO_BET": draw_no_bet(matrix),
        **{f"TOTALS({l})": totals(matrix, l) for l in (1.5, 2.5, 3.5, 4.5, 5.5)},
        "EXACT_SCORE": exact_score(matrix, offered=("0:0", "1:0", "0:1", "other")),
    }

    assert len(projections) == 9
    assert modele.appels == base, "aucune projection ne doit recalculer la distribution"
    for nom, issues in projections.items():
        assert issues, nom


def test_le_cout_croit_avec_les_projections_pas_avec_les_modeles():
    """Deux fois plus de lignes ne doit pas coûter deux fois plus de modèles."""
    contexte = _contexte()
    modele = _ModeleCompteur()
    matrix = modele.distribution(_Event(), contexte["features"], contexte["point_in_time"])

    peu = [totals(matrix, l) for l in (1.5, 2.5)]
    beaucoup = [totals(matrix, l) for l in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5)]

    assert len(beaucoup) == 4 * len(peu)
    assert modele.appels == 1, "le nombre de lignes ne change pas le nombre de modèles"


def test_toutes_les_projections_partagent_la_meme_origine():
    """§15 : la trace de corrélation. Deux marchés d'un même événement issus de
    la même matrice ne sont pas des opportunités indépendantes, et c'est
    `probability_origin` qui permet au sizing de le savoir."""
    pricer = FootballDerivedPricer()
    contexte = _contexte()
    origines = set()
    for famille, params in MARCHES:
        prix = pricer.price(event=_Event(), family=famille,
                            parameters=params, context=contexte)
        assert prix.priced, (famille, params)
        origines.add(prix.probability_origin)
    assert len(origines) == 1, f"une seule origine attendue, vu {origines}"
    assert next(iter(origines)).startswith("dixon_coles:score_matrix:")


def test_le_pricer_ne_recalcule_pas_la_distribution_par_selection():
    """Un marché à 36 issues ne doit pas coûter 36 distributions."""
    pricer = FootballDerivedPricer(base=_ModeleCompteur())
    contexte = _contexte()
    contexte["offered_selections"] = tuple(
        f"{x}:{y}" for y in range(6) for x in range(6) if (x, y) != (5, 5)) + ("other",)

    prix = pricer.price(event=_Event(), family=MarketFamily.EXACT_SCORE,
                        parameters={"source_family_id": 2643}, context=contexte)

    assert len(prix.selections) == 36
    assert pricer._base.appels == 1


@pytest.mark.parametrize("famille,params", MARCHES)
def test_chaque_projection_reste_une_partition(famille, params):
    prix = FootballDerivedPricer().price(
        event=_Event(), family=famille, parameters=params, context=_contexte())
    attendu = 2.0 if famille is MarketFamily.DOUBLE_CHANCE else 1.0
    assert prix.masse_totale == pytest.approx(attendu, abs=1e-9)
