"""CLI `axon clv-collect` — la commande qu'un planificateur appelle en boucle.

`axon record-odds` demandait la phase en argument. C'était juste tant qu'un
humain la choisissait ; ça ne l'est plus dès qu'on veut collecter en continu, car
la bonne phase n'est pas la même pour deux rencontres du même scan — l'une part
dans dix minutes, l'autre demain. Résultat mesuré : 113 décisions, zéro clôture.

Ici, aucune phase à fournir. Le collecteur scanne, situe chaque rencontre par
rapport à son coup d'envoi, et écrit ce qui manque. Lancé toutes les cinq à dix
minutes, il traverse chaque rencontre de la décision à la clôture sans qu'aucune
horloge humaine n'intervienne.

    */5 * * * *  cd <dépôt> && python -m src.agents.quant.betting_engine.clv.collect_cli

Idempotent par construction : relancer ne réécrit rien.
"""

from __future__ import annotations

import argparse
import pathlib
from datetime import datetime, timedelta

from ..bookmakers.winamax.catalogue import multisport_events
from ..sports.registry import SPORT_MODULES, build_event_resolver
from .collect import FENETRE_CLOTURE, HORIZON_DECISION, collect
from .store import JsonlOddsHistoryStore

#: Provenance des cotes écrites par cette commande. Un scan réel, jamais une
#: fixture : la distinction reste lisible dans l'historique.
SOURCE_LIVE = "winamax.fr/live"


def _connecteur():   # pragma: no cover (I/O réseau réelle)
    from ..bookmakers.winamax.connector import WinamaxConnector
    return WinamaxConnector()


def main(argv: list[str] | None = None, *, connector=None,
         store=None, now: datetime | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="axon clv-collect",
        description="Collecte CLV automatique — la phase se déduit du coup d'envoi.")
    p.add_argument("--sports", default=None,
                   help="sports à scanner, séparés par des virgules (défaut : tous "
                        "ceux qui ont un modèle)")
    p.add_argument("--closing-window", type=int, default=int(FENETRE_CLOTURE.total_seconds() // 60),
                   help="minutes avant le coup d'envoi où une cote vaut CLÔTURE")
    p.add_argument("--horizon", type=int, default=int(HORIZON_DECISION.total_seconds() // 3600),
                   help="heures au-delà desquelles une rencontre est trop lointaine")
    p.add_argument("--store", default=None, help="chemin odds_history.jsonl")
    p.add_argument("--run-id", default=None)
    args = p.parse_args(argv)

    sports = ([s.strip() for s in args.sports.split(",") if s.strip()]
              if args.sports else sorted(SPORT_MODULES))
    connecteur = connector if connector is not None else _connecteur()
    historique = store if store is not None else JsonlOddsHistoryStore(
        None if args.store is None else pathlib.Path(args.store))

    # Le scan PROPAGE ses erreurs : une source injoignable est une panne, pas un
    # catalogue vide, et la traiter en silence ferait croire à une collecte saine.
    evenements = multisport_events(connecteur, sports)

    resume = collect(
        evenements, event_resolver=build_event_resolver(), store=historique,
        source=SOURCE_LIVE, now=now,
        fenetre=timedelta(minutes=args.closing_window),
        horizon=timedelta(hours=args.horizon),
        run_id=args.run_id)

    print(f"clv-collect [{', '.join(sports)}] : {resume.describe()}")
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
