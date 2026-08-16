"""`python -m src.agents.quant.betting_engine.outcomes.cli` — état de la boucle.

    status   ce que le modèle a annoncé, ce qui a été réglé, sa justesse réelle
    settle   règle les prédictions en attente depuis le jeu de données tennis

Le règlement est IDEMPOTENT : une prédiction déjà réglée est ignorée, jamais
re-réglée. Relancer après un rafraîchissement du jeu de données ne fait que
rattraper les rencontres devenues disponibles.
"""

from __future__ import annotations

import argparse
import pathlib
from datetime import datetime, timezone

from .calibration import calibration_reelle, rendre_texte
from .settlement import regler_tennis
from .store import JsonlPredictionStore


def _store(chemin: str | None) -> JsonlPredictionStore:
    return JsonlPredictionStore(pathlib.Path(chemin) if chemin else None)


def commande_status(args) -> int:
    store = _store(args.store)
    tous = store.all()
    if not tous:
        print(f"Aucune prédiction enregistrée ({store.path}).")
        print("Le moteur n'a encore rien consigné : la justesse en production "
              "reste non mesurable.")
        return 0

    attente = [r for r in tous if not r.est_reglee]
    print(f"Store : {store.path}")
    print(f"Prédictions : {len(tous)}  ·  réglées {len(tous) - len(attente)}  "
          f"·  en attente {len(attente)}")

    versions = sorted({r.model_version for r in tous})
    for version in versions:
        print(f"\n── {version} ──")
        for ligne in rendre_texte(calibration_reelle(tous, model_version=version)):
            print(f"  {ligne}")

    if attente:
        print(f"\n{len(attente)} en attente de règlement "
              f"— `settle` après rafraîchissement du jeu de données.")
    return 0


def commande_settle(args) -> int:
    store = _store(args.store)
    en_attente = store.non_reglees()
    if not en_attente:
        print("Rien à régler.")
        return 0

    maintenant = datetime.now(timezone.utc)
    total = 0
    for tour in args.tours:
        reglement = regler_tennis(en_attente, tour, now=maintenant)
        for record in reglement.reglees:
            if not args.dry_run:
                store.append(record)
            total += 1
            print(f"  {record.issue.value:8s} {record.selection:12s} "
                  f"{record.stable_event_id}")
        print(f"{tour.upper()} : {reglement.resume}")
        # Une prédiction réglée par un circuit ne doit pas être retentée par l'autre.
        deja = {r.cle for r in reglement.reglees}
        en_attente = [r for r in en_attente if r.cle not in deja]

    print(f"\n{total} règlement(s)" + (" — DRY RUN, rien écrit" if args.dry_run else ""))
    return 0


def main(argv=None) -> int:
    parseur = argparse.ArgumentParser(prog="outcomes", description=__doc__.splitlines()[0])
    parseur.add_argument("--store", help="chemin du JSONL (défaut : var/betting_engine/)")
    sous = parseur.add_subparsers(dest="commande", required=True)

    sous.add_parser("status", help="justesse réelle du modèle").set_defaults(
        fonction=commande_status)

    p_settle = sous.add_parser("settle", help="régler les prédictions en attente")
    p_settle.add_argument("--tours", nargs="+", default=["atp", "wta"])
    p_settle.add_argument("--dry-run", action="store_true",
                          help="montre ce qui serait réglé, sans écrire")
    p_settle.set_defaults(fonction=commande_settle)

    args = parseur.parse_args(argv)
    return args.fonction(args)


if __name__ == "__main__":
    raise SystemExit(main())
