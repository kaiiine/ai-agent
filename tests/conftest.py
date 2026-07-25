"""Fixtures partagées des tests gateway.

Objectif : golden tests hermétiques et rejouables après chaque étape de la
migration Vague 0. Aucun réseau — les réponses brutes des providers sont
enregistrées dans tests/fixtures/, et store/cache/log sont redirigés vers des
DB temporaires pour un déterminisme total.
"""

from __future__ import annotations
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Chemin d'appel football-data.org -> fixture enregistrée.
_FDO_PATH_TO_FIXTURE = {
    "competitions/FL1/matches": "fl1_2025_matches.json",
    "competitions/FL1/standings": "fl1_2025_standings.json",
    "competitions/PL/standings": "pl_2025_standings.json",
}


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def offline_gateway(tmp_path, monkeypatch):
    """Gateway déterministe et sans réseau.

    - football-data.org : `_get` renvoie les réponses brutes enregistrées.
    - point_in_time_store / operational_cache / decision_log : DB temporaires.
    - compteur de quota réinitialisé (évite tout couplage inter-tests).
    """
    from src.agents.quant.gateway.core import point_in_time_store, decision_log, fallback_chain
    from src.agents.quant.gateway.cache import operational_cache
    from src.agents.quant.gateway.registries import provider_coverage_registry
    from src.agents.quant.gateway.providers.football_data_org_provider import FootballDataOrgProvider

    monkeypatch.setattr(point_in_time_store, "STORE_DB", tmp_path / "store.db")
    monkeypatch.setattr(operational_cache, "CACHE_DB", tmp_path / "cache.db")
    monkeypatch.setattr(decision_log, "LOG_FILE", tmp_path / "decisions.log")
    monkeypatch.setattr(fallback_chain, "_request_counts", {})

    # Coverage registry temporaire, seedé avec la baseline vérifiée : sans lui,
    # aucun provider n'est éligible (l'éligibilité est fondée sur la couverture).
    coverage_db = tmp_path / "coverage.db"
    monkeypatch.setattr(provider_coverage_registry, "COVERAGE_DB", coverage_db)
    provider_coverage_registry.seed(db_path=coverage_db)

    def fake_get(self, path, params=None):
        fixture = _FDO_PATH_TO_FIXTURE.get(path)
        if fixture is None:
            raise AssertionError(f"Appel provider non prévu dans les tests : {path}")
        return load_fixture(fixture)

    monkeypatch.setattr(FootballDataOrgProvider, "_get", fake_get)
    yield
