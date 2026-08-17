"""La DA d'Axon, en un seul endroit.

Ces valeurs étaient recopiées dans `ui/panels.py`, `ui/boot.py` et `ui/spec.py` —
trois définitions de `ACCENT = "color(214)"`, donc trois occasions de divergence
le jour où l'orange change. Les modules existants continuent de fonctionner ;
ceux qui arrivent partent d'ici.

Le braille n'est pas un choix esthétique arbitraire : l'axolotl du bandeau
d'accueil est déjà dessiné en braille (`⠀⢀⠐⡄⠰⠤`). Un rendu braille s'inscrit donc
dans une identité qui existe, au lieu de la contredire.
"""
from __future__ import annotations

from rich import box

#: L'orange d'Axon. `color(214)` en indexé, avec son équivalent RGB pour les
#: rendus qui ont besoin d'une vraie valeur (dégradés, moyennes de couleur).
ACCENT = "color(214)"
ACCENT_RGB = (255, 175, 0)

#: Les gris de la DA, tirés des panneaux existants.
FOND = (17, 17, 17)
BORDURE = f"dim {ACCENT}"
SOURD = "dim"
VIF = f"bold {ACCENT}"

#: Le cadre des panneaux. `SIMPLE_HEAD` partout dans l'UI actuelle.
BOITE = box.SIMPLE_HEAD

#: Taille par défaut d'une zone d'aperçu, en cellules de terminal. Choisie pour
#: tenir dans un terminal de 80 colonnes sans repousser le reste de l'affichage.
COLONNES = 72
LIGNES = 20


def titre(texte: str) -> str:
    """Un titre de panneau au format de l'UI existante — sourd, en minuscules."""
    return f"[{SOURD}]{texte}[/{SOURD}]"
