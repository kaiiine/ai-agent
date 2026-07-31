"""CLI `axon providers-discover` (wave 3 §25) — découverte de sources de données pour un
sport/compétition bloqué, via Tavily. Workflow de SETUP/maintenance, JAMAIS le money-path
(§26 : `axon recommend` ne fait aucune recherche web). N'imprime que des POINTEURS à valider.
"""

from __future__ import annotations

import argparse

from .provider_discovery import discover_provider_candidates


def _query(sport: str, competition: str | None) -> str:
    base = f"{sport} historical match results dataset or API — players/teams, dates, results"
    if competition:
        base += f", competition {competition}"
    return base + " ; structured, point-in-time, provenance-verifiable"


def render(candidates) -> list[str]:
    lines = [f"Provider discovery — {len(candidates)} candidat(s) (statut DISCOVERED, à VALIDER) :"]
    for c in candidates:
        lines.append(f"  [{c.structured_access:7} auth={c.auth_required:7}] {c.provider_name}")
        lines.append(f"      {c.source_url}")
    lines.append("  ⚠ Tavily = découverte de sources uniquement — jamais une proba/feature/dataset promu.")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="axon providers-discover",
                                description="Découverte de providers de données (Tavily) — setup, hors money-path.")
    p.add_argument("--sport", required=True)
    p.add_argument("--competition", default=None)
    p.add_argument("--max-results", type=int, default=8)
    args = p.parse_args(argv)
    candidates = discover_provider_candidates(_query(args.sport, args.competition),
                                              max_results=args.max_results)
    for line in render(candidates):
        print(line)
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
