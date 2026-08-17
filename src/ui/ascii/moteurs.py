"""Les moteurs de rendu, du plus fidèle au dernier recours.

Le PRD plaçait chafa en premier. Mesuré sur cette machine, `chafa` n'est PAS
installé — c'est un paquet système — alors que Pillow l'est et figure déjà dans
`requirements.txt`. L'ordre est donc inversé, et le gain va au-delà de la
disponibilité : un moteur en pur Python n'a ni sous-processus, ni fichier
temporaire, ni processus orphelin possible, c'est-à-dire aucun des problèmes que
le PRD énumère comme à éviter.

    demi_bloc   ▀ avec deux couleurs par cellule — le plus fidèle pour une page
    braille     ⣿ monochrome dans l'orange d'Axon — l'identité du produit
    chafa       si le binaire est là, sa qualité reste la meilleure
    etat        aucune image : le texte de ce qu'on sait de la page

Chaque moteur rend `None` au moindre problème. Le registre passe alors au
suivant, et `etat` ne peut pas échouer : il n'a besoin de rien.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from rich.style import Style
from rich.text import Text

from .cadre import Cadre, Moteur
from .palette import ACCENT, SOURD

#: Au-delà, on renonce plutôt que de faire attendre l'utilisateur pour un aperçu.
#: Un aperçu tardif n'informe plus, il gêne.
_DELAI_CHAFA_S = 4.0



def _image(png: bytes):
    """Ouvre les octets en image RGB, ou lève — l'appelant convertit en None."""
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    return img.convert("RGB")


# ── demi-bloc : deux pixels par cellule, en couleurs vraies ───────────────────

class MoteurDemiBloc:
    """Rend chaque cellule comme un « ▀ » : couleur du haut devant, du bas derrière.

    C'est le meilleur compromis pour une capture de page web. Le braille donne
    quatre fois plus de points mais un seul ton par cellule ; sur une maquette,
    ce sont les COULEURS qui portent l'information — un bouton, un bandeau, une
    erreur rouge — pas le tramage.

    Résolution effective : `colonnes` × 2·`lignes` pixels.
    """
    nom = "demi_bloc"

    def disponible(self) -> bool:
        try:
            import PIL  # noqa: F401
            return True
        except Exception:                                        # noqa: BLE001
            return False

    def rendre(self, png: bytes, colonnes: int, lignes: int) -> Cadre | None:
        try:
            from PIL import Image

            img = _image(png).resize((colonnes, lignes * 2), Image.LANCZOS)
            pixels = img.load()
            rendues: list[Text] = []
            for y in range(lignes):
                ligne = Text(no_wrap=True)
                for x in range(colonnes):
                    haut = pixels[x, y * 2]
                    bas = pixels[x, y * 2 + 1]
                    ligne.append("▀", Style(
                        color=f"rgb({haut[0]},{haut[1]},{haut[2]})",
                        bgcolor=f"rgb({bas[0]},{bas[1]},{bas[2]})",
                    ))
                rendues.append(ligne)
            return Cadre(tuple(rendues), self.nom, colonnes, lignes)
        except Exception:                                        # noqa: BLE001
            return None


# ── braille : la signature d'Axon ─────────────────────────────────────────────

#: Le décalage de bit de chaque point braille, indexé [colonne][ligne].
#: L'ordre Unicode n'est pas celui qu'on lit : les points 7 et 8 ont été ajoutés
#: après les six premiers, donc la quatrième rangée porte les bits 6 et 7.
_POINTS = ((0, 1, 2, 6), (3, 4, 5, 7))


class MoteurBraille:
    """Rend en braille monochrome, dans l'orange d'Axon.

    Une cellule braille tient 2 pixels de large et 4 de haut, soit huit fois la
    définition d'un caractère plein. Le prix est la couleur : un seul ton pour
    les huit points. C'est le bon choix pour du trait — un plan, un graphe, une
    animation — et pour rester dans l'identité du bandeau d'accueil.
    """
    nom = "braille"

    def __init__(self, couleur: str = ACCENT):
        self._couleur = couleur

    def disponible(self) -> bool:
        try:
            import PIL  # noqa: F401
            return True
        except Exception:                                        # noqa: BLE001
            return False

    def rendre(self, png: bytes, colonnes: int, lignes: int) -> Cadre | None:
        try:
            from PIL import Image, ImageOps

            img = _image(png).convert("L").resize(
                (colonnes * 2, lignes * 4), Image.LANCZOS)
            # L'autocontraste évite le pavé uniforme sur une page très claire ou
            # très sombre : sans lui, le seuil tombe du même côté partout.
            img = ImageOps.autocontrast(img)
            # Puis un TRAMAGE, pas un seuil. Regardé sur une maquette de page, le
            # seuil fixe perdait tout : le bouton orange (luminance ~180) et les
            # barres de texte gris (~170) passaient du côté clair et n'allumaient
            # aucun point — il ne restait que le bandeau noir. Le tramage rend les
            # demi-tons en DENSITÉ de points, ce qui est exactement la force du
            # braille et fait réapparaître la mise en page.
            img = img.convert("1")
            pixels = img.load()

            style = Style.parse(self._couleur)
            rendues: list[Text] = []
            for cy in range(lignes):
                ligne = Text(no_wrap=True)
                for cx in range(colonnes):
                    masque = 0
                    for dx in range(2):
                        for dy in range(4):
                            if not pixels[cx * 2 + dx, cy * 4 + dy]:
                                masque |= 1 << _POINTS[dx][dy]
                    ligne.append(chr(0x2800 + masque), style)
                rendues.append(ligne)
            return Cadre(tuple(rendues), self.nom, colonnes, lignes)
        except Exception:                                        # noqa: BLE001
            return None


# ── chafa : le meilleur rendu, quand le binaire est là ────────────────────────

class MoteurChafa:
    """Délègue à `chafa`, qui reste la référence en qualité de rendu terminal.

    Trois précautions, chacune répondant à un défaut nommé par le PRD :

      · le fichier temporaire est supprimé dans un `finally`, donc même si chafa
        échoue ou dépasse son délai — pas de fichiers non maîtrisés ;
      · `subprocess.run(timeout=…)` tue le processus enfant avant de lever, donc
        pas d'orphelin ;
      · la sortie est convertie par `Text.from_ansi`, pas insérée telle quelle :
        Rich doit compter la largeur des lignes lui-même, sinon un panneau qui
        l'encadre se décale.
    """
    nom = "chafa"

    def disponible(self) -> bool:
        return shutil.which("chafa") is not None

    def rendre(self, png: bytes, colonnes: int, lignes: int) -> Cadre | None:
        chemin: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(png)
                chemin = Path(f.name)
            proc = subprocess.run(
                ["chafa", "--format=symbols", "--symbols=block+border+space",
                 f"--size={colonnes}x{lignes}", "--animate=off", str(chemin)],
                capture_output=True, timeout=_DELAI_CHAFA_S, check=False,
            )
            if proc.returncode != 0 or not proc.stdout:
                return None
            rendues = tuple(
                Text.from_ansi(l, no_wrap=True)
                for l in proc.stdout.decode("utf-8", "replace").splitlines()
            )
            return Cadre(rendues, self.nom, colonnes, lignes) if rendues else None
        except Exception:                                        # noqa: BLE001
            return None
        finally:
            if chemin is not None:
                chemin.unlink(missing_ok=True)


# ── etat : le dernier recours, qui ne peut pas échouer ────────────────────────

class MoteurEtat:
    """Aucune image — ce qu'on sait de la page, en texte.

    C'est la dégradation gracieuse que le PRD exige : sans moteur graphique,
    l'utilisateur doit voir l'état de la page, pas une erreur ni un vide. Ce
    moteur n'a besoin de rien, donc il est toujours disponible et ne rend jamais
    `None`.
    """
    nom = "etat"

    def disponible(self) -> bool:
        return True

    def rendre(self, png: bytes, colonnes: int, lignes: int) -> Cadre | None:
        return self.depuis_etat({}, colonnes, lignes)

    def depuis_etat(self, etat: dict, colonnes: int, lignes: int) -> Cadre:
        champs = [
            ("url", etat.get("url", "—")),
            ("titre", etat.get("titre", "—")),
            ("action", etat.get("action", "—")),
        ]
        # `max(…, 16)` parce qu'une zone étroite rendait `colonnes - 12` NÉGATIF,
        # et qu'une tranche négative coupe par la FIN : « http://x » devenait
        # « http ». Mieux vaut déborder un peu que tronquer à l'envers.
        largeur = max(colonnes - 12, 16)
        rendues = []
        for cle, valeur in champs:
            ligne = Text(no_wrap=True)
            ligne.append(f"  {cle:8}", style=SOURD)
            ligne.append(str(valeur)[:largeur], style="white")
            rendues.append(ligne)
        if (erreurs := etat.get("erreurs")):
            ligne = Text(no_wrap=True)
            ligne.append("  console ", style=SOURD)
            ligne.append(f"{erreurs} erreur(s)", style="red")
            rendues.append(ligne)
        return Cadre(tuple(rendues), self.nom, colonnes, len(rendues),
                     etiquette="aperçu indisponible", meta=dict(etat))


# ── Registre ──────────────────────────────────────────────────────────────────

#: Du plus fidèle au dernier recours. `etat` ferme la liste et ne renonce jamais,
#: ce qui garantit qu'il y a TOUJOURS un moteur — le sidecar n'a donc pas de cas
#: « aucun rendu possible » à gérer.
_ORDRE: tuple[Moteur, ...] = (
    MoteurDemiBloc(),
    MoteurBraille(),
    MoteurChafa(),
    MoteurEtat(),
)


def moteurs_disponibles() -> tuple[Moteur, ...]:
    return tuple(m for m in _ORDRE if m.disponible())


def choisir(prefere: str = "") -> Moteur:
    """Le moteur à utiliser : celui demandé s'il est là, sinon le meilleur présent.

    Un nom inconnu ou indisponible ne lève pas : on retombe sur l'ordre par
    défaut. Un réglage mal orthographié doit dégrader l'aperçu, pas la session.
    """
    disponibles = moteurs_disponibles()
    if prefere:
        for m in disponibles:
            if m.nom == prefere:
                return m
    return disponibles[0] if disponibles else MoteurEtat()


def rendre(png: bytes, colonnes: int, lignes: int, prefere: str = "") -> Cadre | None:
    """Tente le moteur choisi, puis les suivants. Rend `None` si tous renoncent.

    L'enchaînement compte : un PNG tronqué fait échouer Pillow, et sans ce repli
    l'aperçu resterait figé sur l'image d'avant sans que personne sache pourquoi.
    """
    prioritaire = choisir(prefere)
    for m in (prioritaire, *(x for x in moteurs_disponibles() if x is not prioritaire)):
        if (cadre := m.rendre(png, colonnes, lignes)) is not None:
            return cadre
    return None
