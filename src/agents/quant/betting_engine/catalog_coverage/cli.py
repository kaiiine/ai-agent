"""`axon catalog-coverage` — quelle part du catalogue AXON sait-il évaluer ?

    status    dernière mesure, sport par sport
    history   évolution de la couverture globale entre les runs

Les chiffres viennent d'un run réel. Sans run enregistré, la commande le DIT au
lieu d'afficher des zéros qui ressembleraient à une couverture nulle mesurée.
"""

from __future__ import annotations

import argparse
import pathlib

from .store import JsonlCoverageStore


def _pct(v) -> str:
    return "n/m" if v is None else f"{v * 100:.1f} %"


def _n(v) -> str:
    return "n/m" if v is None else str(v)


def commande_status(args) -> int:
    store = JsonlCoverageStore(pathlib.Path(args.store) if args.store else None)
    derniere = store.derniere()
    if derniere is None:
        print(f"NOT_MEASURED — aucune mesure de couverture enregistrée ({store.path}).")
        print("Lance un scan réel : la mesure s'écrit toute seule à la fin du run.")
        return 0

    print(f"AXON CATALOG COVERAGE — mesuré le {derniere['measured_at'][:19]}")
    print(f"  fenêtre : {derniere.get('window_start')} → {derniere.get('window_end')}")
    if not derniere.get("catalog_reachable", True):
        print("  ⚠ catalogue non atteint sur ce run : les totaux sont des minorants.")
    print()
    entete = (f"  {'sport':<16}{'catalog':>9}{'résolu':>9}{'évalué':>9}"
              f"{'review':>9}{'action.':>9}{'couv.':>9}")
    print(entete)
    print("  " + "-" * (len(entete) - 2))
    for s in derniere["sports"]:
        print(f"  {s['sport']:<16}{_n(s['catalog_events_seen']):>9}"
              f"{s['competition_resolved']:>9}{s['evaluated']:>9}"
              f"{s['review_only']:>9}{s['actionable']:>9}"
              f"{_pct(s['evaluation_rate']):>9}")
        for code, nombre in sorted(s.get("blockers", {}).items(), key=lambda kv: -kv[1])[:3]:
            print(f"      · {nombre:4d}  {code}")
    print(f"\n  GLOBAL : {_n(derniere['total_catalog_events'])} au catalogue · "
          f"{derniere['total_evaluated']} évaluée(s) · "
          f"{derniere['total_actionable']} actionnable(s) · "
          f"couverture {_pct(derniere['global_coverage'])}")
    return 0


def commande_history(args) -> int:
    store = JsonlCoverageStore(pathlib.Path(args.store) if args.store else None)
    mesures = store.all()
    if not mesures:
        print("NOT_MEASURED — aucun run enregistré.")
        return 0
    print(f"{'date':<21}{'catalogue':>11}{'évalué':>9}{'actionnable':>13}{'couverture':>12}")
    print("-" * 66)
    for m in mesures[-args.limite:]:
        print(f"{m['measured_at'][:19]:<21}{_n(m['total_catalog_events']):>11}"
              f"{m['total_evaluated']:>9}{m['total_actionable']:>13}"
              f"{_pct(m['global_coverage']):>12}")
    return 0


def main(argv=None) -> int:
    parseur = argparse.ArgumentParser(prog="catalog-coverage",
                                      description=__doc__.splitlines()[0])
    parseur.add_argument("--store", help="chemin du JSONL (défaut : var/betting_engine/)")
    sous = parseur.add_subparsers(dest="commande", required=True)
    sous.add_parser("status", help="dernière mesure").set_defaults(fonction=commande_status)
    p_hist = sous.add_parser("history", help="évolution entre les runs")
    p_hist.add_argument("--limite", type=int, default=20)
    p_hist.set_defaults(fonction=commande_history)
    args = parseur.parse_args(argv)
    return args.fonction(args)


if __name__ == "__main__":
    raise SystemExit(main())
