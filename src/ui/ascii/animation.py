"""Animations ASCII réutilisables — le second usage du centre, après l'aperçu.

Tu voulais pouvoir étendre l'ASCII au-delà de l'agent code. Une animation n'a
rien à voir avec une capture de page, mais elle partage tout le reste : la DA, la
zone `Live`, et la règle qu'un affichage ne doit jamais peser sur ce qu'il
accompagne. D'où un `Animation` qui expose la même interface qu'un `Cadre` — un
`__rich__` — et qui se pilote par le temps plutôt que par événements.

Le braille sert ici sa vraie force : huit points par cellule, donc du mouvement
fin sans occuper d'espace. C'est ce que l'axolotl du bandeau fait déjà, en fixe.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from rich.panel import Panel
from rich.text import Text

from .palette import ACCENT, BOITE, BORDURE, SOURD, titre

#: Les huit phases d'un point qui tourne, en braille. Chaque caractère n'allume
#: qu'un point, ce qui donne une rotation lisible sur une seule cellule.
ROTATION = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧")

#: Un remplissage progressif, du vide au plein.
REMPLISSAGE = ("⠀", "⡀", "⣀", "⣄", "⣤", "⣦", "⣶", "⣷", "⣿")


@dataclass
class Animation:
    """Une animation pilotée par l'horloge, pas par un compteur d'appels.

    Se fonder sur le temps et non sur le nombre d'affichages est ce qui rend la
    vitesse indépendante du taux de rafraîchissement : la même animation tourne
    à la même allure dans une zone `Live` à 4 Hz et à 20 Hz.
    """
    images: tuple[str, ...]
    periode: float = 0.8
    libelle: str = ""
    style: str = ACCENT
    _origine: float = field(default_factory=time.monotonic, repr=False)

    def image(self, instant: float | None = None) -> str:
        maintenant = instant if instant is not None else time.monotonic()
        avance = ((maintenant - self._origine) / self.periode) % 1.0
        return self.images[int(avance * len(self.images)) % len(self.images)]

    def __rich__(self) -> Text:
        t = Text()
        t.append(f"  {self.image()}  ", style=f"bold {self.style}")
        if self.libelle:
            t.append(self.libelle, style=SOURD)
        return t


def rotation(libelle: str = "") -> Animation:
    return Animation(ROTATION, periode=0.8, libelle=libelle)


def remplissage(libelle: str = "") -> Animation:
    return Animation(REMPLISSAGE, periode=1.6, libelle=libelle)


@dataclass
class Onde:
    """Une vague braille qui traverse la largeur — pour une attente longue.

    Elle existe parce qu'un point qui tourne dit « ça travaille » sans dire
    « ça avance ». Sur une opération de plusieurs dizaines de secondes, un motif
    qui se déplace se lit comme une progression, là où une rotation se lit comme
    un blocage.
    """
    largeur: int = 32
    periode: float = 2.2
    libelle: str = ""
    _origine: float = field(default_factory=time.monotonic, repr=False)

    def __rich__(self) -> Text:
        avance = ((time.monotonic() - self._origine) / self.periode) % 1.0
        t = Text("  ")
        for x in range(self.largeur):
            phase = math.sin((x / self.largeur - avance) * math.tau)
            niveau = int((phase + 1) / 2 * (len(REMPLISSAGE) - 1))
            t.append(REMPLISSAGE[niveau],
                     style=f"bold {ACCENT}" if niveau > 4 else f"dim {ACCENT}")
        if self.libelle:
            t.append("  ")
            t.append(self.libelle, style=SOURD)
        return t


def panneau(contenu, etiquette: str = "") -> Panel:
    """Encadre n'importe quel renderable ASCII dans la DA d'Axon.

    Un seul endroit décide de la boîte, de la bordure et de la position du titre :
    sans ça, chaque nouvel usage réinventerait un panneau légèrement différent et
    l'interface se mettrait à jurer avec elle-même.
    """
    return Panel(contenu, box=BOITE, border_style=BORDURE,
                 title=titre(etiquette) if etiquette else None,
                 title_align="left", padding=(0, 1))
