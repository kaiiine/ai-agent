# src/infra/incident_cli.py
"""`axon incidents` — capturer et relire les erreurs constatées.

    axon incidents              les incidents déjà capturés
    axon incidents --capturer   relire la trace et en déduire les nouveaux
    axon incidents --projet X   ne garder que ce dépôt
    axon incidents --categorie routing

La capture est MANUELLE, et volontairement. L'automatiser avant d'avoir vu ce
qu'elle produit reviendrait à faire confiance à une déduction que personne n'a
encore relue ; c'est aussi ce qui garde la boucle hors du chemin critique d'un
tour, où elle n'a rien à faire.

Le filtre `--projet` n'est pas un confort d'affichage : le fichier est global
pour servir d'un projet à l'autre, mais une leçon de routage apprise sur le
catalogue d'un dépôt peut ne rien vouloir dire dans un autre. Pouvoir isoler un
projet est la condition pour ne pas généraliser ce qui n'est pas généralisable.
"""
from __future__ import annotations

import argparse
from collections import Counter

from rich.console import Console
from rich.table import Table

from src.infra import incident, trace
from src.ui.ascii.palette import ACCENT, BOITE, SOURD

console = Console()

#: Couleur par catégorie. `routing` est la seule que la trace attribue
#: mécaniquement — les autres sont soit déduites d'un refus, soit absentes.
_TEINTES = {
    incident.ROUTING: ACCENT,
    incident.EXECUTION: "yellow",
    incident.PLAN: SOURD,
    incident.ETAT_PERIME: SOURD,
}


def _table(*colonnes: str) -> Table:
    table = Table(box=BOITE, border_style=f"dim {ACCENT}", header_style=ACCENT,
                  pad_edge=False)
    for nom in colonnes:
        table.add_column(nom, justify="left", overflow="fold")
    return table


def _rendre(incidents: list[dict]) -> None:
    table = _table("quand", "projet", "catégorie", "demande", "correction")
    for ligne in incidents:
        categorie = str(ligne.get("categorie") or "")
        # La demande d'abord, ce qui a été tenté en dessous et en sourdine : sans
        # la demande, la ligne dit CE qui a raté sans dire à quoi ça répondait,
        # et une relecture six mois plus tard ne peut rien en conclure.
        demande = str(ligne.get("intention_reformulee") or "—")[:60]
        tente = str(ligne.get("action_tentee") or "").strip()[:60]
        table.add_row(
            str(ligne.get("horodatage") or "")[:16].replace("T", " "),
            str(ligne.get("projet") or trace.HORS_REPO),
            f"[{_TEINTES.get(categorie, SOURD)}]{categorie}[/]",
            f"{demande}\n[{SOURD}]{tente}[/]" if tente else demande,
            # Une correction vide est affichée comme telle, jamais comblée : un
            # incident sans correction est un incident dont personne n'a encore
            # dit ce qu'il aurait fallu faire, et c'est une information.
            str(ligne.get("correction") or "—")[:44],
        )
    console.print()
    console.print(table)


def _resume(incidents: list[dict]) -> None:
    categories = Counter(str(i.get("categorie") or "?") for i in incidents)
    projets = Counter(str(i.get("projet") or trace.HORS_REPO) for i in incidents)
    sans = sum(1 for i in incidents if not str(i.get("correction") or "").strip())
    console.print(f"\n  [{SOURD}]{len(incidents)} incident(s)  ·  " + "  ".join(
        f"{nom}×{n}" for nom, n in categories.most_common()) + "[/]")
    console.print("  [" + SOURD + "]projets : " + "  ".join(
        f"{nom}×{n}" for nom, n in projets.most_common()) + "[/]")
    # Le chiffre qui dit si la boucle sert : un incident sans correction ne
    # deviendra jamais une règle, il ne fait qu'archiver. Tu ne le vois que
    # lorsqu'il y en a — annoncer « 0 sans correction » à chaque affichage
    # userait l'avertissement jusqu'à ce que plus personne ne le lise.
    if sans:
        console.print(f"  [{SOURD}]{sans} sans correction — "
                      f"rien à promouvoir tant que personne n'a dit quoi faire[/]")


def main(argv: list[str]) -> int:
    parseur = argparse.ArgumentParser(
        prog="axon incidents",
        description="Les erreurs constatées, déduites de la trace de décision.")
    parseur.add_argument("--capturer", action="store_true",
                         help="relire la trace et en déduire les incidents nouveaux")
    parseur.add_argument("--projet", default="",
                         help="ne garder que ce dépôt")
    parseur.add_argument("--categorie", default="",
                         help="routing | plan | execution | etat_perime")
    parseur.add_argument("--tout", action="store_true",
                         help="tout afficher au lieu des 20 derniers")
    args = parseur.parse_args(argv)

    if args.capturer:
        nouveaux = incident.capturer()
        if not nouveaux:
            console.print(f"\n  [{SOURD}]rien de nouveau — la trace ne porte aucun "
                          f"signal qui ne soit déjà capturé[/]\n")
            return 0
        console.print(f"\n  [{ACCENT}]{len(nouveaux)} incident(s) capturé(s)[/]")

    incidents = incident.lire()
    if args.projet:
        incidents = [i for i in incidents if i.get("projet") == args.projet]
    if args.categorie:
        incidents = [i for i in incidents if i.get("categorie") == args.categorie]

    if not incidents:
        console.print(f"\n  [{SOURD}]aucun incident — "
                      f"`axon incidents --capturer` en déduit de la trace[/]\n")
        return 0

    _rendre(incidents if args.tout else incidents[-20:])
    _resume(incidents)
    console.print()
    return 0
