"""Diagnostic CLI de la gateway (GW-FR-011).

- `axon sports-status` : vue d'ensemble providers + compétitions installées.
- `axon sports-status --competition <id> --season <y>` : couverture RÉELLE par
  data_type (lue dans le provider_coverage_registry).
- `axon sports-seed` : bootstrap du coverage registry (baseline vérifiée).

Aucun appel réseau : lit métadonnées providers + registres locaux.
"""

from __future__ import annotations
import os

from src.agents.quant.gateway.core.provider_registry import REGISTRY, FALLBACK_ORDER
from src.agents.quant.gateway.gateway import current_season
from src.agents.quant.gateway.registries import competition_registry as cr
from src.agents.quant.gateway.registries import provider_coverage_registry as pcr

_KEY_ENV_VAR = {"football_data_org": "FOOTBALL_DATA_ORG_KEY", "api_sports": "API_FOOTBALL_KEY"}


def _providers_overview() -> None:
    season = current_season()
    for sport, order in FALLBACK_ORDER.items():
        print(f"── {sport} (fallback : {' → '.join(order)}) ──")
        for name in order:
            entry = REGISTRY.get(name)
            if entry is None:
                continue
            provider = entry.provider
            caps = provider.capabilities(sport)
            has_key = bool(os.environ.get(_KEY_ENV_VAR.get(name, ""), "")) if name in _KEY_ENV_VAR else True
            symbol = "✓" if has_key else "⚠"
            print(f"  {symbol} {name}  clé={has_key}  "
                  f"caps: fixtures={caps.fixtures} standings={caps.standings}  "
                  f"coût={provider.query_cost}  quota={provider.get_rate_limit_status()}")
        print()


def _competitions_overview() -> None:
    print("── compétitions installées (competition_registry) ──")
    for comp in cr.COMPETITIONS.values():
        print(f"  {comp.canonical_id}  [{comp.status}]  {comp.name} ({comp.country_code})")
    print("\n  → détail couverture : axon sports-status --competition <id> --season <y>\n")


def _coverage_detail(competition_id: str, season: str) -> None:
    comp = cr.get_competition(competition_id)
    if comp is None:
        print(f"  ✗ compétition inconnue : {competition_id!r}")
        print(f"    compétitions valides : {', '.join(cr.COMPETITIONS)}")
        return

    print(f"── couverture : {comp.name} ({competition_id}) · saison {season} ──")
    entries = pcr.all_coverage(competition_id, season)
    if not entries:
        print("  (aucune entrée de couverture — lance `axon sports-seed` pour bootstrapper)")
        return

    by_data_type: dict[str, list] = {}
    for e in entries:
        by_data_type.setdefault(e.data_type, []).append(e)

    for data_type in sorted(by_data_type):
        print(f"  {data_type}")
        for e in by_data_type[data_type]:
            usable = "utilisable" if e.status in ("FULL", "PARTIAL") else "NON utilisable"
            print(f"      {e.provider:20} {e.status.value:11} ({usable})  "
                  f"prov_id={e.provider_competition_id}  vérifié={e.verification_method} le {e.verified_at.date()}")
    print()


def print_status(competition: str | None = None, season: str | None = None) -> None:
    season = season or current_season()
    print(f"\nAxon Sports Data Gateway — saison courante : {current_season()}\n")
    if competition:
        _coverage_detail(competition, season)
    else:
        _providers_overview()
        _competitions_overview()


def seed_coverage() -> None:
    n = pcr.seed()
    print(f"✓ coverage registry seedé : {n} entrées écrites dans {pcr.COVERAGE_DB}")
