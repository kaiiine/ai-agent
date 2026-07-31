"""CLI `axon coverage` (§16) : rend observable `catalogue coverage ≠ model coverage`.

Scanne Winamax (live ou replay d'une capture), regroupe par compétition, et affiche
pour chacune : découverte, canonicalisation, modèle disponible, maturité, et la RAISON
de non-évaluabilité. Un sport/compétition non supporté est ISOLÉ (jamais évalué en
silence, jamais arrêtant le scan). Aucune donnée fabriquée.
"""

from __future__ import annotations

import argparse
import pathlib

from .bookmakers.winamax.catalogue import all_events
from .capability import coverage_matrix


def _scan(args):
    if args.capture:
        from .bookmakers.winamax.record_replay import load_capture, replay
        cap = load_capture(pathlib.Path(args.capture))
        return replay(cap), f"replay:{cap.source}"
    from .bookmakers.winamax.connector import WinamaxConnector
    return all_events(WinamaxConnector(), args.sport), "winamax.fr/live"


def render(matrix, source: str) -> list[str]:
    # Couches DISTINCTES (§19) : catalogue ≠ data ≠ model ≠ SUPPORTED. `model-capable`
    # peut dépasser `data-capable` (ex. MLS : modèle football applicable mais aucune
    # donnée) — c'est précisément la distinction que le produit doit rendre visible.
    lines = [
        f"Couverture {matrix.sport} [{source}]",
        f"  compétitions découvertes : {matrix.competitions_discovered}  (events : {matrix.events_discovered})",
        f"  model-capable : {matrix.competitions_model_capable}   "
        f"data-capable : {matrix.competitions_data_capable}   "
        f"ÉVALUABLES : {matrix.competitions_evaluable}  (events : {matrix.events_evaluable})",
        f"  par état de capacité : {matrix.by_state}",
        f"  non évaluables par raison : {matrix.by_reason}",
        "  — évaluables —",
    ]
    for c in matrix.capabilities:
        if c.evaluable:
            lines.append(f"    {c.competition_name[:32]:32} {c.maturity:12} {c.discovered_events:3} events  {c.canonical_competition}")
    if matrix.competitions_evaluable == 0:
        lines.append("    (aucune — catalogue large mais aucun modèle applicable)")
    lines.append("  — non évaluables (top 10 par volume) —")
    for c in [x for x in matrix.capabilities if not x.evaluable][:10]:
        lines.append(f"    {c.competition_name[:32]:32} {c.capability_state:18} {c.reason_unavailable:24} {c.discovered_events:3} events")
    return lines


def render_all_sports(cov) -> list[str]:
    lines = [
        f"Couverture UNIVERSELLE [winamax.fr/live] — {cov.sports_discovered} sports découverts",
        f"  model-capable : {cov.sports_model_capable}   SUPPORTED : {cov.sports_supported}",
        f"  {'sportId':>7}  {'sport':22} {'modèle':16} {'issues':6} {'maturité':12} bloqueur",
    ]
    for r in cov.rows:
        model = r.methodology or "—"
        outc = str(r.outcomes) if r.outcomes else "—"
        lines.append(f"  {r.winamax_sport_id:>7}  {r.sport_name[:22]:22} {model:16} {outc:6} "
                     f"{r.maturity:12} {r.blocker or ''}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="axon coverage", description="Couverture Winamax -> modèle (§16/§24).")
    p.add_argument("--sport", default="football")
    p.add_argument("--capture", default=None, help="rejouer une capture (offline) au lieu du live")
    p.add_argument("--all-sports", action="store_true",
                   help="matrice UNIVERSELLE : tous les sports Winamax découverts × modèles validés")
    args = p.parse_args(argv)

    if args.all_sports:
        from .bookmakers.winamax.connector import WinamaxConnector
        from .universal_coverage import universal_coverage
        cov = universal_coverage(WinamaxConnector().discover_sports())
        for line in render_all_sports(cov):
            print(line)
        return 0

    events, source = _scan(args)
    matrix = coverage_matrix(events, args.sport)
    for line in render(matrix, source):
        print(line)
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
