"""CLI `axon tennis-inventory --dir <path> --tour atp|wta` (Unité B §1/§2).

Commande à donner à l'utilisateur pour FOURNIR ses CSV Jeff Sackmann locaux et obtenir
l'inventaire (provenance/checksum/période/qualité/point-in-time). Aucun téléchargement :
si le répertoire manque ou est vide, la commande échoue explicitement.
"""

from __future__ import annotations

import argparse

from .dataset_loader import load_sackmann_dir
from .inventory import render


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="axon tennis-inventory",
        description="Inventorie un dataset tennis Sackmann LOCAL (aucun téléchargement).")
    p.add_argument("--dir", required=True, help="répertoire contenant atp_matches_*.csv / wta_matches_*.csv")
    p.add_argument("--tour", required=True, choices=("atp", "wta"))
    args = p.parse_args(argv)
    try:
        ds = load_sackmann_dir(args.dir, args.tour)
    except (FileNotFoundError, ValueError) as exc:
        print(f"dataset indisponible : {exc}")
        return 1
    for line in render(ds):
        print(line)
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
