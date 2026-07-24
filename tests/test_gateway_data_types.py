"""Verrou du vocabulaire fermé des data_type (PRD v2 §5.2)."""

from __future__ import annotations

from src.agents.quant.gateway.canonical.data_types import DataType, is_valid_data_type

# Vocabulaire attendu — figé. Ajouter/retirer un type est une décision explicite
# (impacte provider_coverage_registry et fallback_chain), donc doit casser ce test.
EXPECTED = {
    "FIXTURES", "RESULTS", "STANDINGS", "TEAM_STATS", "PLAYER_STATS",
    "LINEUPS", "INJURIES", "RANKINGS", "HEAD_TO_HEAD_RAW", "SQUAD",
}


def test_closed_vocabulary_is_exactly_the_spec():
    assert {dt.value for dt in DataType} == EXPECTED


def test_fixtures_and_results_are_distinct():
    # Arbitrage Vague 0 : à venir vs terminé sont deux types séparés.
    assert DataType.FIXTURES != DataType.RESULTS


def test_is_valid_data_type():
    assert is_valid_data_type("STANDINGS") is True
    assert is_valid_data_type("fixtures") is False   # sensible à la casse
    assert is_valid_data_type("GOALS") is False


def test_enum_value_is_str():
    # str Enum : utilisable directement comme chaîne dans une CanonicalEnvelope.
    assert DataType.RESULTS == "RESULTS"
