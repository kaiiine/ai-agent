"""Diagnostic CLI — `axon sports-status` (F6). Pas d'appel réseau : lit les
métadonnées déclarées par chaque provider (capabilities, is_available, quota).
"""

from __future__ import annotations
import os

from src.agents.quant.gateway.core.provider_registry import REGISTRY, FALLBACK_ORDER
from src.agents.quant.gateway.gateway import current_season

_KEY_ENV_VAR = {"football_data_org": "FOOTBALL_DATA_ORG_KEY", "api_sports": "API_FOOTBALL_KEY"}


def print_status() -> None:
    season = current_season()
    print(f"\nAxon Sports Data Gateway — saison courante : {season}\n")

    for sport, order in FALLBACK_ORDER.items():
        print(f"── {sport} (fallback : {' → '.join(order)}) ──")
        for name in order:
            entry = REGISTRY.get(name)
            if entry is None:
                continue
            provider = entry.provider
            caps = provider.capabilities(sport)
            season_available = provider.is_available(sport, season)
            has_key = bool(os.environ.get(_KEY_ENV_VAR.get(name, ""), "")) if name in _KEY_ENV_VAR else True

            symbol = "✓" if (season_available and has_key) else "⚠"
            print(f"  {symbol} {name}")
            print(f"      clé configurée   : {has_key}")
            print(f"      saison {season} disponible : {season_available}")
            print(f"      capabilities     : fixtures={caps.fixtures} standings={caps.standings}")
            print(f"      coût / requête   : {provider.query_cost}")
            print(f"      quota            : {provider.get_rate_limit_status()}")
            print(f"      doc              : {entry.doc_url}")
        print()
