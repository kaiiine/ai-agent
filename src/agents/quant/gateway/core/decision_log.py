"""Journal structuré des décisions de fallback — un JSON par ligne (F8, audit ultérieur)."""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path.home() / ".axon" / "sports_gateway_decisions.log"


def log_decision(
    sport: str,
    endpoint: str,
    league_canonical_id: str,
    season: str,
    chosen_provider: str | None,
    reason: str,
    errors: list[str],
) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sport": sport,
        "endpoint": endpoint,
        "league": league_canonical_id,
        "season": season,
        "chosen_provider": chosen_provider,
        "reason": reason,
        "errors": errors,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
