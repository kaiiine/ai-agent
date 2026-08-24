"""Le centre ASCII d'Axon : aperçus, animations, art, une seule DA.

Organisation, du général au particulier :

    palette     la DA — une seule définition de l'orange et de la boîte
    cadre       `Cadre` (un rendu figé) et le protocole `Moteur`
    moteurs     demi_bloc · braille · chafa · etat, du plus fidèle au repli
    sidecar     `SidecarAscii` : zone événementielle, coalescée, non bloquante
    animation   animations pilotées par l'horloge, et l'encadrement `panneau()`
    scenes      art fixe (l'axolotl, le navigateur vide)
    navigateur  `ObservateurNavigateur` : le premier consommateur du sidecar

Le sidecar ne sait rien d'un navigateur : il reçoit un producteur d'images et
affiche. C'est ce qui permet d'ajouter d'autres observateurs — une progression de
build, un graphe de paris, un rendu de slide — sans y retoucher.

Règle non négociable, tirée du PRD : rien de ce paquet ne retourne de contenu
destiné au modèle. Le seul chemin de sortie est `__rich__`, vers l'affichage.
"""
from __future__ import annotations

from .animation import Animation, Onde, panneau, remplissage, rotation
from .cadre import Cadre, Moteur
from .moteurs import choisir, moteurs_disponibles, rendre
from .palette import ACCENT, BOITE, BORDURE, COLONNES, LIGNES
from .sidecar import Reglages, SidecarAscii

__all__ = [
    "ACCENT", "BOITE", "BORDURE", "COLONNES", "LIGNES",
    "Cadre", "Moteur", "rendre", "choisir", "moteurs_disponibles",
    "SidecarAscii", "Reglages",
    "Animation", "Onde", "rotation", "remplissage", "panneau",
]


