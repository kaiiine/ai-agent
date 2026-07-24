"""Tests du contrat SportModule et du registre (PRD v2 §6, GW-NFR-006)."""

from __future__ import annotations

import pytest

from src.agents.quant.gateway.sports.registry import (
    SportModule,
    SPORT_MODULES,
    get_sport_module,
    UnsupportedSportError,
)


class _FakeFootballModule:
    """Implémentation minimale conforme au protocole, pour tester le mécanisme
    sans dépendre du vrai module football (livré à C1)."""
    sport = "football"
    schema_version = "football/1.0"

    def supported_data_types(self) -> set[str]:
        return {"RESULTS", "STANDINGS"}

    def normalizers(self) -> dict[str, object]:
        return {}

    def validate_payload(self, payload: object, data_type: str) -> None:
        return None

    def entity_types(self) -> set[str]:
        return {"team"}

    def derived_calculators(self) -> dict[str, object]:
        return {}

    def is_schema_compatible(self, stored_schema_version: str) -> bool:
        return stored_schema_version == self.schema_version


def test_registry_is_empty_in_wave0():
    # Vague 0 : aucun sport encore installé (football arrive à C1).
    assert SPORT_MODULES == {}


def test_get_sport_module_raises_on_unknown():
    with pytest.raises(UnsupportedSportError) as exc:
        get_sport_module("__inconnu__")
    assert exc.value.sport == "__inconnu__"


def test_registration_and_retrieval_mechanism(monkeypatch):
    module = _FakeFootballModule()
    monkeypatch.setitem(SPORT_MODULES, "football", module)
    assert get_sport_module("football") is module


def test_fake_module_satisfies_protocol():
    # SportModule est runtime_checkable : conformité structurelle vérifiable.
    assert isinstance(_FakeFootballModule(), SportModule)


def test_isolation_unknown_sport_does_not_leak(monkeypatch):
    # Un sport installé n'empêche pas de rejeter proprement un autre (GW-NFR-006).
    monkeypatch.setitem(SPORT_MODULES, "football", _FakeFootballModule())
    with pytest.raises(UnsupportedSportError):
        get_sport_module("tennis")
