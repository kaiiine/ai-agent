"""Ce qu'un moteur de rendu produit, et le contrat qu'il respecte.

Un `Cadre` est un rendu FIGÉ : des segments Rich prêts à afficher, plus de quoi
dire d'où il vient. Il ne contient ni image, ni chemin de fichier, ni handle de
processus — c'est ce qui permet au sidecar de le garder en mémoire sans retenir
de ressource, et de supprimer la capture aussitôt convertie.

Le `Protocole Moteur` existe pour que la première implémentation ne devienne pas
la seule possible. Le PRD demandait chafa derrière une interface ; l'interface
est ici, et chafa n'en est qu'un des membres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rich.text import Text


@dataclass(frozen=True)
class Cadre:
    """Un rendu ASCII prêt à afficher.

    `lignes` porte des `Text` Rich et non des chaînes ANSI brutes : c'est Rich qui
    doit connaître les couleurs, sinon il compte mal la largeur des lignes et
    l'affichage se décale dès qu'un panneau les encadre.
    """
    lignes: tuple[Text, ...]
    moteur: str
    colonnes: int
    lignes_hautes: int
    etiquette: str = ""
    meta: dict = field(default_factory=dict)

    def __rich__(self) -> Text:
        joint = Text()
        for i, ligne in enumerate(self.lignes):
            if i:
                joint.append("\n")
            joint.append_text(ligne)
        return joint

    @property
    def vide(self) -> bool:
        return not self.lignes


@runtime_checkable
class Moteur(Protocol):
    """Convertit une image en `Cadre`, ou renonce proprement.

    Trois règles, et la troisième est la plus importante :

      · `disponible()` ne doit rien coûter — elle est appelée au démarrage pour
        choisir le moteur, pas pour rendre ;
      · `rendre()` reçoit des octets PNG et une taille en CELLULES de terminal,
        jamais en pixels : c'est au moteur de savoir combien de pixels tient une
        de ses cellules ;
      · `rendre()` rend `None` plutôt que de lever. Un aperçu qui échoue doit
        laisser sa place au moteur suivant, pas interrompre ce qu'il observe.
    """
    nom: str

    def disponible(self) -> bool: ...

    def rendre(self, png: bytes, colonnes: int, lignes: int) -> Cadre | None: ...
