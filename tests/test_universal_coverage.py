"""Couverture universelle tous-sports (wave 3 §20/§22/§24/§32) — hermétique.

Prouve : tout sport Winamax découvert apparaît ; un sport sans modèle validé est
SIGNALÉ (SPORT_DISCOVERED_MODEL_UNAVAILABLE), jamais ignoré ; un NOUVEAU sport inconnu
est automatiquement flaggé ; MarketSchema est déjà N-way (binary/ternary/N).
"""

from __future__ import annotations

from src.agents.quant.betting_engine.bookmakers.winamax.connector import sports_from_state
from src.agents.quant.betting_engine.core.market_model import MarketSchema
from src.agents.quant.betting_engine.universal_coverage import (
    SPORT_DISCOVERED_MODEL_UNAVAILABLE,
    universal_coverage,
)

# Catalogue Winamax simulé (sortie réelle de discover_sports), incl. un sport FUTUR inconnu.
_DISCOVERED = {1: "Football", 2: "Basketball", 3: "Baseball", 4: "Hockey sur glace",
               5: "Tennis", 16: "Football américain", 23: "Volley-ball", 777: "Kabaddi"}


def test_sports_from_state_parses_ids():
    state = {"sports": {"1": {"sportName": "Football"}, "5": {"sportName": "Tennis"}, "x": {}}}
    assert sports_from_state(state) == {1: "Football", 5: "Tennis"}


def test_every_discovered_sport_appears():
    cov = universal_coverage(_DISCOVERED)
    assert cov.sports_discovered == len(_DISCOVERED)          # rien n'est perdu
    assert {r.winamax_sport_id for r in cov.rows} == set(_DISCOVERED)


def test_validated_models_are_model_capable_experimental():
    cov = universal_coverage(_DISCOVERED)
    by_id = {r.winamax_sport_id: r for r in cov.rows}
    for sid in (1, 2, 3, 16, 23):                            # football/basket/baseball/NFL/volley
        assert by_id[sid].model_capable is True
        assert by_id[sid].maturity == "EXPERIMENTAL"         # dérivé du ledger, jamais SUPPORTED
        assert by_id[sid].blocker is None
    assert cov.sports_model_capable == 5 and cov.sports_supported == 0


def test_unmodeled_and_new_sports_are_flagged_not_ignored():
    cov = universal_coverage(_DISCOVERED)
    by_id = {r.winamax_sport_id: r for r in cov.rows}
    for sid in (4, 5, 777):                                  # hockey/tennis + Kabaddi (nouveau)
        assert by_id[sid].model_capable is False
        assert by_id[sid].blocker == SPORT_DISCOVERED_MODEL_UNAVAILABLE
    assert by_id[777].sport_name == "Kabaddi"                # sport futur inconnu, visible (§32)


def test_market_schema_is_already_n_way():
    # §22 : le contrat OutcomeSpace est déjà N-way (2/3/N) sans changer l'aval.
    two = MarketSchema("MONEYLINE", "2way", ("home", "away"), ("slot_1", "slot_2"), False)
    three = MarketSchema("MATCH_WINNER", "3way", ("home", "draw", "away"), ("draw", "slot_1", "slot_2"), True)
    nway = MarketSchema("PODIUM", "4way", ("p1", "p2", "p3", "p4"), ("s1", "s2", "s3", "s4"), False)
    assert len(two.selections) == 2 and len(three.selections) == 3 and len(nway.selections) == 4
    assert nway.selections == ("p1", "p2", "p3", "p4")       # N-way structurellement supporté
