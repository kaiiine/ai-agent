"""L'art ASCII fixe d'Axon, rassemblé.

L'axolotl et son ciel vivaient dans `ui/panels.py`, au milieu des fonctions de
panneaux. Ils sont ici pour que le prochain dessin ait un endroit évident où
aller, et pour que `panels.py` puisse les importer sans les contenir.

`panels.py` garde volontairement sa propre copie pour l'instant : la déplacer
demanderait de toucher au bandeau d'accueil, ce qui n'a rien à voir avec l'aperçu
navigateur. Les deux se rejoindront quand quelqu'un touchera au bandeau — et la
duplication est signalée ici plutôt que découverte plus tard.
"""
from __future__ import annotations

from rich.align import Align
from rich.console import Group
from rich.text import Text

from .palette import ACCENT, SOURD

#: L'axolotl, en braille. C'est cette scène qui fait du braille l'identité
#: visuelle d'Axon, et qui justifie qu'un moteur de rendu braille existe.
AXOLOTL: tuple[tuple[str, str], ...] = (
    ("  *        ░░░░░░░                   *        *    ", SOURD),
    ("      ░░   ░░░░░░░░░░░        *                    ", SOURD),
    ("    ░░░░░░░░░░░░░░░░░░░     ░░░░░░░░░          *   ", SOURD),
    ("  *                        ░░░░░░░░░░░░░░           ", SOURD),
    ("              *            ░░░░░░░░░░░░░░░░    *    ", SOURD),
    ("⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⠐⡄⠰⠤⠀⠀⠀⠀⠀⠀", f"bold {ACCENT}"),
    ("⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢐⠹⣀⣆⠚⠂⢱⡀⠀⠀⠀⠀", f"bold {ACCENT}"),
    ("⢀⢀⡄⡀⢄⠀⡠⠔⠊⠉⠉⠉⠉⢲⣷⡿⣠⣗⣡⠂⠀⠀", f"bold {ACCENT}"),
    ("⡘⣈⢣⡰⣈⠎⠀⠀⠀⠀⠀⢿⣦⡀⢙⣟⣽⢁⡜⡠⡨⢤", f"bold {ACCENT}"),
    ("⢱⠒⡏⢯⣿⢷⢀⠴⡶⠊⠁⠀⠀⠁⠀⢹⠛⢏⢫⠐⠁⠃", f"bold {ACCENT}"),
    ("⠂⣁⠼⣾⣿⠉⠀⠀⠀⠀⠀⢎⠍⠒⠴⠧⠯⡈⠉⠀⠀⡄", f"bold {ACCENT}"),
    ("⠀⠣⠕⡞⣹⡗⣤⠄⠀⠀⠀⠀⠁⠀⠀⠀⠀⠈⢉⡵⢠⠃", f"bold {ACCENT}"),
    ("⠀⠀⠀⠈⠀⠀⠑⠀⠤⠤⠤⢄⠀⠀⠀⠀⠠⢞⡓⠈⣀⠄", f"bold {ACCENT}"),
    ("⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠑⠒⠒⠈⠉⠁⠀⠀⠀", f"bold {ACCENT}"),
    ("  ───────────────────────────────────────  ", SOURD),
)

#: Un navigateur stylisé, affiché quand aucune page n'a encore été ouverte : une
#: zone vide dit « rien ne marche », un cadre vide dit « rien à montrer encore ».
NAVIGATEUR_VIDE: tuple[tuple[str, str], ...] = (
    ("  ╭────────────────────────────────────╮  ", SOURD),
    ("  │ ⣿⣿⣿  ⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀  │  ", SOURD),
    ("  ├────────────────────────────────────┤  ", SOURD),
    ("  │                                    │  ", SOURD),
    ("  │        aucune page ouverte         │  ", SOURD),
    ("  │                                    │  ", SOURD),
    ("  ╰────────────────────────────────────╯  ", SOURD),
)


def scene(lignes: tuple[tuple[str, str], ...], centrer: bool = True) -> Group:
    """Rend une scène. `centrer` parce qu'un dessin décentré se remarque plus
    qu'un dessin absent."""
    rendues = [
        Align.center(Text(texte, style=style)) if centrer
        else Text(texte, style=style)
        for texte, style in lignes
    ]
    return Group(*rendues)
