"""CLI `axon record-odds` : entrypoint câblé + collecte réelle depuis une capture.

Hermétique : on écrit une capture SYNTHÉTIQUE sur disque, on lance le CLI dessus, et on
vérifie que les observations sont persistées avec la bonne provenance. Prouve que la
collecte odds_history est OPÉRATIONNELLE (offline) — pas seulement une infra dormante.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agents.quant.betting_engine.bookmakers.winamax.record_replay import (
    save_capture,
    synthetic_capture,
)
from src.agents.quant.betting_engine.clv import JsonlOddsHistoryStore, clv_readiness
from src.agents.quant.betting_engine.clv.cli import main as record_odds_cli

_KO_EPOCH = 1772359200


def _fl1_state(home_odds):
    return {
        "matches": {"77001": {
            "sportId": 1, "tournamentId": 4, "isOutright": False,
            "competitor1Id": 1301, "competitor1Name": "Paris Saint-Germain",
            "competitor2Id": 1302, "competitor2Name": "Marseille",
            "matchStart": _KO_EPOCH, "status": "PREMATCH"}},
        "bets": {"9001": {"matchId": 77001, "betType": 1, "betTypeName": "Résultat",
                          "template": "3way", "betTypeIsLive": False, "outcomes": [501, 502, 503]}},
        "outcomes": {"501": {"code": "1", "label": "PSG"}, "502": {"code": "x", "label": "Nul"},
                     "503": {"code": "2", "label": "OM"}},
        "odds": {"501": home_odds, "502": 4.30, "503": 6.10},
        "tournaments": {"4": {"tournamentName": "Ligue 1"}}}


def _write_capture(tmp_path, home_odds, name="cap.json"):
    path = tmp_path / name
    save_capture(synthetic_capture(_fl1_state(home_odds), "football"), path)
    return path


def test_cli_records_from_capture_file(tmp_path):
    cap = _write_capture(tmp_path, 2.10)
    store_path = tmp_path / "odds.jsonl"
    code = record_odds_cli([
        "--capture", str(cap), "--phase", "decision", "--store", str(store_path),
        "--now", "2026-03-01T10:00:00+00:00", "--run-id", "r1"])
    assert code == 0
    obs = JsonlOddsHistoryStore(store_path).all()
    assert len(obs) == 3                                 # home/draw/away
    assert all(o.source == "synthetic" for o in obs)     # provenance honnête
    assert all(o.run_id == "r1" for o in obs)


def test_cli_decision_then_closing_accumulates_measurable_clv(tmp_path):
    store_path = tmp_path / "odds.jsonl"
    dec = _write_capture(tmp_path, 2.10, "dec.json")
    clo = _write_capture(tmp_path, 1.90, "clo.json")

    # Coup d'envoi de la capture : 10:00 UTC. La clôture était prise à 17:30, soit
    # sept heures et demie APRÈS — une cote de direct étiquetée « clôture ».
    record_odds_cli(["--capture", str(dec), "--phase", "decision", "--store", str(store_path),
                     "--now", "2026-02-28T10:00:00+00:00"])
    record_odds_cli(["--capture", str(clo), "--phase", "closing", "--store", str(store_path),
                     "--now", "2026-03-01T09:55:00+00:00"])

    readiness = clv_readiness(JsonlOddsHistoryStore(store_path).all())
    assert readiness.status == "MEASURABLE"
    assert readiness.n_complete_pairs == 3
