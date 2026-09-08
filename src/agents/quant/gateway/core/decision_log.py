"""Journal structuré des décisions de fallback — un JSON par ligne (GW-NFR-003).

Chaque requête expose : provider sélectionné, candidats considérés + écartés avec
raison, fallback utilisé ou non, cache hit/miss, latence, data_quality,
freshness_score/degraded, quota restant. Schéma stable (champs None si N/A) pour
que l'audit ultérieur soit requêtable.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from src.infra import chemins as _chemins

LOG_FILE = _chemins.journal_decisions()


def log_decision(
    sport: str,
    data_type: str,
    competition_id: str,
    season: str,
    chosen_provider: str | None,
    reason: str,
    errors: list[str],
    *,
    candidates: list[str] | None = None,
    fallback_used: bool | None = None,
    cache: str | None = None,             # "hit" | "miss" | None
    latency_ms: float | None = None,
    data_quality: float | None = None,
    freshness_score: float | None = None,
    freshness_degraded: bool | None = None,
    quota: dict | None = None,
) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sport": sport,
        "data_type": data_type,
        "competition": competition_id,
        "season": season,
        "reason": reason,
        "chosen_provider": chosen_provider,
        "candidates_considered": candidates or [],
        "rejected": errors,                 # "provider: raison" pour chaque candidat écarté
        "fallback_used": fallback_used,
        "cache": cache,
        "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        "data_quality": data_quality,
        "freshness_score": freshness_score,
        "freshness_degraded": freshness_degraded,
        "quota": quota,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
