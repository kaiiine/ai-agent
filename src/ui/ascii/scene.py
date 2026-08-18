"""Deux colonnes : le journal à gauche, l'aperçu ancré à droite.

La droite de l'écran est vide pendant tout un build, et l'aperçu y a sa place —
plutôt que de défiler au milieu des lignes d'outils, où il passe et disparaît.

Le point d'appui est que `run_build(project_name, console)` REÇOIT sa console.
Il suffit donc de lui en passer une autre, qui écrit dans une mise en page au lieu
du terminal : ses trente-et-un `console.print` n'ont pas à changer, et aucune
autre partie du build ne sait que l'affichage a bougé.

Un compromis assumé, parce qu'il n'a pas de solution propre : une zone `Live` qui
tient l'écran REDESSINE sa surface à chaque rafraîchissement. Les lignes sorties
du journal ne partent donc pas dans l'historique du terminal — on ne peut plus
remonter au début d'un build de vingt minutes. C'est le prix de l'ancrage à
droite ; `apercu_colonnes: 0` rend l'affichage classique, qui garde tout.
"""
from __future__ import annotations

from collections import deque

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from .palette import BOITE, BORDURE, SOURD, titre

#: En dessous, la colonne de gauche devient trop étroite pour une ligne d'outil :
#: on renonce à l'ancrage plutôt que de rendre le journal illisible pour un
#: aperçu. Mesuré sur les lignes les plus longues du build (chemins de fichiers).
_LARGEUR_MINIMALE = 118

#: Marges de la zone `Live` : le titre du build, les règles de phase, l'invite.
_RESERVE_VERTICALE = 6


class SceneBuild:
    """Une façade de console qui range ce qu'on lui imprime dans deux colonnes.

    Elle n'expose que `print` parce que c'est tout ce que `run_build` utilise —
    vérifié, trente-et-un appels et aucune autre méthode. Ajouter le reste de
    l'interface de `Console` donnerait l'illusion d'un remplaçant complet.
    """

    def __init__(self, console, *, largeur_apercu: int = 46):
        self._console = console
        self._largeur = largeur_apercu
        self._journal: deque = deque(maxlen=400)
        self._apercu = None
        self._live: Live | None = None
        self._actif = False

    # ── Décision d'ancrer, ou pas ─────────────────────────────────────────────

    @property
    def ancrable(self) -> bool:
        """L'ancrage n'a de sens que si les DEUX colonnes restent lisibles."""
        return (self._largeur > 0
                and self._console.width >= _LARGEUR_MINIMALE
                and self._console.height >= 20)

    @property
    def colonnes_apercu(self) -> int:
        """La largeur utile pour la capture — bordures et marges déduites.

        Elle pilote la taille demandée au moteur de rendu : capturer plus large
        que la colonne ferait rogner l'image par Rich, capturer plus étroit
        laisserait un bord vide.
        """
        return max(self._largeur - 4, 20)

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def __enter__(self) -> "SceneBuild":
        if self.ancrable:
            self._live = Live(self._rendu(), console=self._console,
                              refresh_per_second=6, vertical_overflow="crop",
                              transient=False)
            self._live.__enter__()
            self._actif = True
        return self

    def __exit__(self, *exc) -> None:
        if self._live is not None:
            try:
                self._live.update(self._rendu())
            finally:
                self._live.__exit__(*exc)
        self._actif = False
        self._live = None

    # ── Entrées ───────────────────────────────────────────────────────────────

    def print(self, *objets, **kwargs) -> None:
        """La façade. Hors ancrage, elle laisse passer vers la vraie console."""
        if not self._actif:
            self._console.print(*objets, **kwargs)
            return
        for o in (objets or ("",)):
            self._journal.append(o)
        self._rafraichir()

    def poser_apercu(self, renderable) -> None:
        """Remplace l'aperçu de droite. Hors ancrage, l'imprime au fil de l'eau."""
        if not self._actif:
            self._console.print(renderable)
            return
        self._apercu = renderable
        self._rafraichir()

    # ── Rendu ─────────────────────────────────────────────────────────────────

    def _rafraichir(self) -> None:
        if self._live is not None:
            try:
                self._live.update(self._rendu())
            except Exception:                                    # noqa: BLE001
                pass

    def _hauteur_journal(self) -> int:
        return max(self._console.height - _RESERVE_VERTICALE, 8)

    def _rendu(self) -> Layout:
        racine = Layout()
        racine.split_row(
            Layout(self._panneau_journal(), name="journal"),
            Layout(self._panneau_apercu(), name="apercu", size=self._largeur),
        )
        return racine

    def _panneau_journal(self) -> Panel:
        # Seules les dernières lignes sont rendues : au-delà, Rich mesurerait
        # quatre cents renderables à chaque rafraîchissement pour n'en montrer
        # qu'une vingtaine.
        visibles = list(self._journal)[-self._hauteur_journal():]
        return Panel(Group(*visibles) if visibles else Text(""),
                     box=BOITE, border_style=BORDURE, padding=(0, 1))

    def _panneau_apercu(self) -> Panel:
        if self._apercu is not None:
            return Panel(self._apercu, box=BOITE, border_style=BORDURE,
                         title=titre("aperçu"), title_align="left", padding=(0, 0))
        from .scenes import NAVIGATEUR_VIDE, scene
        return Panel(scene(NAVIGATEUR_VIDE), box=BOITE, border_style=BORDURE,
                     title=titre("aperçu"), title_align="left", padding=(1, 0))
