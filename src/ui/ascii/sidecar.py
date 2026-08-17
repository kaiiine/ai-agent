"""Une zone d'affichage ASCII alimentée par ÉVÉNEMENTS, jamais par sondage.

C'est la pièce réutilisable : elle ne sait rien d'un navigateur. On lui donne un
producteur — une fonction qui rend des octets d'image, ou rien — et elle s'occupe
du reste : ne pas bloquer l'appelant, fusionner les demandes qui s'accumulent,
espacer les rendus, et ne jamais faire échouer ce qu'elle observe.

Les quatre garanties, dans l'ordre où elles comptent :

  1. `demander()` ne bloque JAMAIS. Elle pose une intention et rend la main. Un
     agent qui attend son aperçu serait un agent ralenti par son affichage ;
  2. les demandes sont COALESCÉES : dix demandes pendant un rendu en cours n'en
     produisent qu'un seul de plus, avec le motif le plus récent. Sans cela, une
     rafale d'actions navigateur ferait la queue et l'aperçu afficherait le
     passé pendant des secondes ;
  3. deux rendus sont espacés d'au moins `intervalle_min`, ce qui borne le coût
     CPU et supprime le scintillement ;
  4. rien de ce qui se passe ici ne remonte en exception. Un aperçu est un
     confort ; il n'a pas le droit d'interrompre le travail.

Ce que le sidecar ne fait pas, et ne doit pas faire : il ne rend son contenu à
personne d'autre qu'à l'affichage. Aucune méthode ne retourne de texte destiné à
un modèle — c'est la contrainte centrale du PRD, et elle est vérifiée par un test.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from rich.panel import Panel
from rich.text import Text

from .cadre import Cadre
from .moteurs import MoteurEtat, rendre
from .palette import BOITE, BORDURE, COLONNES, LIGNES, SOURD, titre

#: Le producteur rend les octets d'une image, ou None s'il n'a rien à montrer.
Producteur = Callable[[], bytes | None]

#: L'état textuel affiché quand aucune image n'est disponible.
FournisseurEtat = Callable[[], dict]


@dataclass(frozen=True)
class Reglages:
    """Ce qui gouverne le sidecar, groupé pour être passé d'un bloc.

    `intervalle_min` est le seul réglage sensible : trop bas il fait scintiller
    et chauffer, trop haut l'aperçu montre une page qu'on a déjà quittée. 0,6 s
    tient les deux — assez lent pour ne pas peser, assez vif pour suivre un
    enchaînement de clics.
    """
    colonnes: int = COLONNES
    lignes: int = LIGNES
    intervalle_min: float = 0.6
    moteur: str = ""
    etiquette: str = "navigateur"

    #: Rythme de capture spontanée, sans événement. 0 le désactive et rend le
    #: sidecar purement événementiel.
    #:
    #: Une capture coûte 47 ms mesurés — 34 de MCP, 12 de rendu — sur un fil qui
    #: n'est pas celui de l'agent, et n'occupe la session Playwright que 34 ms.
    #: Un battement d'une seconde pèse donc 5 % d'un fil de fond ; ce n'est pas
    #: ce qui limite.
    #:
    #: Ce qui limite, c'est l'utilité : pendant un build, la page reste immobile
    #: la plupart du temps, et la recapturer cent fois pour afficher la même
    #: image ne montre rien de plus. D'où l'espacement automatique ci-dessous.
    battement: float = 1.2
    #: Quand deux captures donnent la MÊME image, l'intervalle DOUBLE jusqu'à
    #: cette borne ; il repart au minimum dès que l'image change. Une page qui
    #: bouge est donc suivie de près, une page figée est presque gratuite.
    battement_max: float = 20.0


class SidecarAscii:
    """Un aperçu ASCII événementiel, coalescé et silencieux."""

    def __init__(self, producteur: Producteur, *,
                 etat: FournisseurEtat | None = None,
                 reglages: Reglages | None = None,
                 actif: Callable[[], bool] | None = None):
        self._producteur = producteur
        self._etat = etat or (lambda: {})
        #: Le battement ne bat QUE si l'observateur dit qu'il y a quelque chose à
        #: regarder. Sans ce garde, on demanderait des captures avant la première
        #: navigation, et longtemps après la fermeture du navigateur.
        self._actif = actif or (lambda: False)
        self._r = reglages or Reglages()

        self._verrou = threading.Lock()
        self._reveil = threading.Event()
        self._arret = threading.Event()
        self._motif_en_attente: str | None = None
        self._cadre: Cadre | None = None
        self._dernier_rendu = 0.0
        self._compte = 0
        self._fusionnees = 0
        self._spontanees = 0
        self._empreinte: int | None = None
        self._attente = 0.0
        self._fil: threading.Thread | None = None

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def demarrer(self) -> None:
        """Lance le fil de rendu. Idempotent : deux appels ne font qu'un fil.

        Le fil est `daemon` : si la session se termine sans passer par
        `arreter()`, il ne retient pas le processus. Un aperçu ne doit pas
        empêcher Axon de rendre la main.
        """
        with self._verrou:
            if self._fil is not None and self._fil.is_alive():
                return
            self._arret.clear()
            self._fil = threading.Thread(
                target=self._boucle, name="axon-ascii", daemon=True)
            self._fil.start()

    def arreter(self, delai: float = 1.0) -> None:
        self._arret.set()
        self._reveil.set()
        fil = self._fil
        if fil is not None and fil.is_alive():
            fil.join(timeout=delai)

    def __enter__(self) -> "SidecarAscii":
        self.demarrer()
        return self

    def __exit__(self, *_) -> None:
        self.arreter()

    # ── Entrée : une demande d'aperçu ─────────────────────────────────────────

    def demander(self, motif: str = "") -> None:
        """Signale qu'il y aurait quelque chose de nouveau à montrer.

        Ne bloque pas, ne rend rien, ne lève rien. Si un rendu est déjà en cours
        ou trop récent, la demande est simplement mémorisée — et une demande qui
        en remplace une autre incrémente `fusionnees`, ce qui rend la coalescence
        observable au lieu d'être une intention.
        """
        with self._verrou:
            if self._motif_en_attente is not None:
                self._fusionnees += 1
            self._motif_en_attente = motif or self._r.etiquette
        self._reveil.set()

    # ── Sortie : uniquement vers l'affichage ──────────────────────────────────

    @property
    def cadre(self) -> Cadre | None:
        with self._verrou:
            return self._cadre

    @property
    def statistiques(self) -> dict:
        """De quoi mesurer le sidecar sans l'instrumenter — utile en test et en
        diagnostic : combien de rendus, et combien de demandes fusionnées."""
        with self._verrou:
            return {
                "rendus": self._compte,
                "fusionnees": self._fusionnees,
                "spontanees": self._spontanees,
                # Deux décimales : à une seule, `round(0.05, 1)` vaut 0.1 et un
                # battement rapide devenait indistinguable de son double.
                "battement": round(self._attente, 2),
                "moteur": self._cadre.moteur if self._cadre else None,
            }

    def __rich__(self) -> Panel:
        """Le renderable pour une zone `Live`. C'est la SEULE sortie du sidecar."""
        cadre = self.cadre
        if cadre is None or cadre.vide:
            corps: Text | Cadre = Text("  aperçu en attente…", style=SOURD)
            etiquette = self._r.etiquette
        else:
            corps = cadre
            etiquette = f"{self._r.etiquette} · {cadre.moteur}"
            if cadre.etiquette:
                etiquette += f" · {cadre.etiquette}"
        return Panel(corps, box=BOITE, border_style=BORDURE,
                     title=titre(etiquette), title_align="left", padding=(0, 1))

    # ── Le fil de rendu ───────────────────────────────────────────────────────

    def _boucle(self) -> None:
        while not self._arret.is_set():
            self._reveil.wait(timeout=0.25)
            self._reveil.clear()
            if self._arret.is_set():
                return

            with self._verrou:
                motif = self._motif_en_attente
                self._motif_en_attente = None
            if motif is None:
                motif = self._battement_du()
            if motif is None:
                continue

            # L'espacement se fait ICI et non à la demande : une demande arrivée
            # trop tôt n'est pas jetée, elle attend son tour. La jeter perdrait
            # justement le dernier état, celui qui compte.
            attente = self._r.intervalle_min - (time.monotonic() - self._dernier_rendu)
            if attente > 0:
                if self._arret.wait(timeout=attente):
                    return

            self._rendre_une_fois(motif)

    def _battement_du(self) -> str | None:
        """Faut-il capturer spontanément, sans événement ?

        Trois conditions, et chacune évite un gaspillage réel : un battement
        configuré, quelque chose à regarder (une page ouverte), et l'intervalle
        courant écoulé. Cet intervalle N'EST PAS fixe — il double à chaque image
        identique, ce qui rend une page figée presque gratuite tout en suivant de
        près une page qui bouge.
        """
        if self._r.battement <= 0:
            return None
        try:
            if not self._actif():
                return None
        except Exception:                                        # noqa: BLE001
            return None
        if self._attente <= 0:
            self._attente = self._r.battement
        if time.monotonic() - self._dernier_rendu < self._attente:
            return None
        with self._verrou:
            self._spontanees += 1
        return "battement"

    def _rendre_une_fois(self, motif: str) -> None:
        """Produit puis convertit. Toute panne devient une vue d'état, pas une erreur."""
        cadre: Cadre | None = None
        try:
            png = self._producteur()
            if png:
                # L'empreinte décide du rythme : une image identique à la
                # précédente signifie que la page ne bouge pas, donc qu'il est
                # inutile de la redemander aussi vite. On compare les OCTETS,
                # avant rendu — c'est plus fidèle que comparer l'ASCII, qui perd
                # les petits changements en réduisant l'image.
                empreinte = hash(png)
                if empreinte == self._empreinte:
                    self._attente = min(max(self._attente, self._r.battement) * 2,
                                        self._r.battement_max)
                else:
                    self._attente = self._r.battement
                self._empreinte = empreinte
                cadre = rendre(png, self._r.colonnes, self._r.lignes, self._r.moteur)
        except Exception:                                        # noqa: BLE001
            cadre = None

        if cadre is None:
            try:
                etat = dict(self._etat())
            except Exception:                                    # noqa: BLE001
                etat = {}
            etat.setdefault("action", motif)
            cadre = MoteurEtat().depuis_etat(etat, self._r.colonnes, self._r.lignes)

        with self._verrou:
            self._cadre = cadre
            self._compte += 1
        self._dernier_rendu = time.monotonic()
