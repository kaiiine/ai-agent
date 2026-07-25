"""Tests du journal structuré des décisions (GW-NFR-003)."""

from __future__ import annotations
import json


def test_decision_log_record_has_all_nfr003_fields(tmp_path, monkeypatch):
    from src.agents.quant.gateway.core import decision_log
    monkeypatch.setattr(decision_log, "LOG_FILE", tmp_path / "d.log")

    decision_log.log_decision(
        "football", "STANDINGS", "competition:football:fra:ligue1", "2025",
        "football_data_org", "LIVE_FETCH", ["api_sports: quota_exhausted"],
        candidates=["football_data_org", "api_sports"], fallback_used=True, cache="miss",
        latency_ms=12.34, data_quality=0.9, freshness_score=0.8, freshness_degraded=False,
        quota={"local_used": 1, "local_limit": 8},
    )
    record = json.loads((tmp_path / "d.log").read_text().strip())
    for field in ("timestamp", "sport", "data_type", "competition", "season", "reason",
                  "chosen_provider", "candidates_considered", "rejected", "fallback_used",
                  "cache", "latency_ms", "data_quality", "freshness_score", "freshness_degraded", "quota"):
        assert field in record, f"champ GW-NFR-003 manquant : {field}"
    assert record["candidates_considered"] == ["football_data_org", "api_sports"]
    assert record["rejected"] == ["api_sports: quota_exhausted"]
    assert record["latency_ms"] == 12.3   # arrondi


def test_decision_log_enriched_on_live_fetch(offline_gateway):
    from src.agents.quant.gateway.core.fallback_chain import fetch_league_data
    from src.agents.quant.gateway.core import decision_log
    from src.agents.quant.gateway.gateway import _resolver

    fetch_league_data(sport="football", data_type="STANDINGS",
                      league_canonical_id="competition:football:fra:ligue1", season="2025", resolver=_resolver)

    record = json.loads(decision_log.LOG_FILE.read_text().strip().splitlines()[-1])
    assert record["reason"] == "LIVE_FETCH"
    assert record["chosen_provider"] == "football_data_org"
    assert record["candidates_considered"] == ["football_data_org"]   # api_sports ABSENT en 2025
    assert record["cache"] == "miss"
    assert record["latency_ms"] is not None
    assert record["data_quality"] == 0.9
    assert record["freshness_degraded"] is True                        # fdo standings sans published_time
    assert record["quota"]["local_used"] >= 1
