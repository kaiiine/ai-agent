"""Smoke tests du CLI diagnostic (GW-FR-011)."""

from __future__ import annotations


def test_status_overview_lists_providers_and_competitions(capsys):
    from src.agents.quant.gateway import status
    status.print_status()
    out = capsys.readouterr().out
    assert "football_data_org" in out
    assert "competition:football:fra:ligue1" in out


def test_status_coverage_detail_by_data_type(tmp_path, monkeypatch, capsys):
    from src.agents.quant.gateway.registries import provider_coverage_registry as pcr
    from src.agents.quant.gateway import status

    monkeypatch.setattr(pcr, "COVERAGE_DB", tmp_path / "cov.db")
    pcr.seed(db_path=tmp_path / "cov.db")

    status.print_status(competition="competition:football:fra:ligue1", season="2025")
    out = capsys.readouterr().out
    assert "STANDINGS" in out
    assert "football_data_org" in out and "FULL" in out
    assert "api_sports" in out and "ABSENT" in out       # tier gratuit, visible dans le diagnostic


def test_status_unknown_competition_is_reported(capsys):
    from src.agents.quant.gateway import status
    status.print_status(competition="competition:football:xxx:inconnue", season="2025")
    out = capsys.readouterr().out
    assert "inconnue" in out.lower() or "inconnu" in out.lower()


def test_status_empty_coverage_hints_seed(tmp_path, monkeypatch, capsys):
    from src.agents.quant.gateway.registries import provider_coverage_registry as pcr
    from src.agents.quant.gateway import status
    monkeypatch.setattr(pcr, "COVERAGE_DB", tmp_path / "empty.db")
    status.print_status(competition="competition:football:fra:ligue1", season="2025")
    out = capsys.readouterr().out
    assert "sports-seed" in out
