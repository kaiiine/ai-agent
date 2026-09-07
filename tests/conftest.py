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


@pytest.fixture(autouse=True)
def trace_hors_du_home(tmp_path, monkeypatch):
    """La trace de décision écrit dans un répertoire temporaire, jamais sous `~/`.

    `trace.inscrire` n'a aucune I/O à l'import (cf. docs/dette.md), mais il écrit
    à l'APPEL — et c'est correct : c'est ce que prescrit DETTE-001 pour
    `checkpoint.py`. Reste que tout test qui fait tourner le vrai graphe déposait
    alors ses lignes dans le `~/.axon/decisions.jsonl` de la machine. Mesuré :
    `tests/test_catalogue.py` y a écrit 26 lignes, dont un rattrapage
    `jira_create_issue` sur une requête météo — de quoi fausser la première vraie
    mesure de `axon trace --route`.

    Le correctif est local aux tests, pas au module, exactement comme le dit
    docs/dette.md du cas `test_us_leagues_live`. Posé une fois ici plutôt que
    dans chaque fichier : un test ajouté demain hérite de la protection sans
    savoir qu'elle existe.
    """
    from src.infra import incident, langfuse_export, trace

    monkeypatch.setattr(trace, "FICHIER", tmp_path / "decisions.jsonl")
    monkeypatch.setattr(langfuse_export, "REPERE", tmp_path / "langfuse.json")
    # Même raison pour le journal d'incidents : `capturer()` écrit à l'appel, et
    # un test qui le déclenche déposerait ses lignes dans le `~/.axon/` de la
    # machine. Le trou s'ajoute ici et pas dans chaque fichier, pour qu'un test
    # écrit demain hérite de la protection sans savoir qu'elle existe.
    monkeypatch.setattr(incident, "FICHIER", tmp_path / "incidents.jsonl")


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
