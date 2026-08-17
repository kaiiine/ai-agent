"""L'observateur Playwright : le premier consommateur du sidecar ASCII.

Il regarde passer les appels d'outils du navigateur et, après ceux qui changent
ce qu'on VOIT, demande une capture. Il ne décide d'aucune navigation, ne touche à
aucun résultat d'outil, et ne rend son rendu qu'à l'affichage.

Trois pièges, tous dans le code plutôt qu'en commentaire d'intention :

  · sa propre capture est un appel d'outil navigateur. Sans exclusion explicite,
    observer `browser_take_screenshot` déclencherait une capture, qui en
    déclencherait une autre — une boucle qui ne s'arrête jamais ;
  · lire la console ou l'arbre d'accessibilité ne change RIEN à l'écran. Y
    répondre par une capture coûterait un aller-retour pour réafficher la même
    image ;
  · le fichier de capture nous appartient — nous en imposons le chemin — donc le
    supprimer est sûr. Supprimer un fichier que l'utilisateur a demandé serait
    une faute ; c'est pourquoi le nom est tiré d'un répertoire temporaire à nous.
"""
from __future__ import annotations

import base64
import binascii
import re
import shutil
import threading
import uuid
from pathlib import Path

from .sidecar import Reglages, SidecarAscii

#: Le préfixe de tous les outils du serveur Playwright MCP.
PREFIXE = "playwright__"

#: L'outil de capture. Exclu des déclencheurs, sans quoi il s'auto-appelle.
CAPTURE = f"{PREFIXE}browser_take_screenshot"

#: Les actions dont le SUCCÈS change l'écran. Nommées une par une : une liste
#: fondée sur un préfixe attraperait les lectures et les captures elles-mêmes.
ACTIONS_VISIBLES: frozenset[str] = frozenset({
    f"{PREFIXE}{nom}" for nom in (
        "browser_navigate", "browser_navigate_back", "browser_click",
        "browser_type", "browser_fill_form", "browser_press_key",
        "browser_select_option", "browser_hover", "browser_drag",
        "browser_drop", "browser_file_upload", "browser_tabs",
        "browser_resize", "browser_wait_for", "browser_handle_dialog",
        "browser_evaluate",
    )
})

#: Ce qui lit sans modifier. Explicite pour que la distinction se relise, et
#: pour qu'un futur outil de lecture soit ajouté ici sans hésitation.
LECTURES: frozenset[str] = frozenset({
    f"{PREFIXE}{nom}" for nom in (
        "browser_snapshot", "browser_console_messages", "browser_network_requests",
        "browser_network_request", "browser_find", "browser_take_screenshot",
    )
})


def _png_depuis(resultat) -> bytes | None:
    """Extrait des octets PNG d'un résultat MCP, quelle qu'en soit la forme.

    Les serveurs MCP ne s'accordent pas : certains rendent du base64 dans un bloc
    de contenu, d'autres écrivent un fichier et n'en rendent que le chemin,
    d'autres encore une liste de blocs typés. Plutôt que de parier sur une forme
    et de casser à la première mise à jour du serveur, on reconnaît celles qu'on
    rencontre et on rend `None` pour le reste — le sidecar affichera l'état.
    """
    if resultat is None:
        return None
    if isinstance(resultat, (bytes, bytearray)):
        return bytes(resultat)

    if isinstance(resultat, dict):
        for cle in ("data", "image", "base64", "content"):
            if (valeur := resultat.get(cle)) is not None:
                if (png := _png_depuis(valeur)) is not None:
                    return png
        for cle in ("path", "filename", "file"):
            if (chemin := resultat.get(cle)):
                return _png_depuis(str(chemin))
        return None

    if isinstance(resultat, (list, tuple)):
        for element in resultat:
            if (png := _png_depuis(element)) is not None:
                return png
        return None

    if isinstance(resultat, str):
        texte = resultat.strip()
        if not texte:
            return None
        # Un chemin de fichier : la forme la plus courante côté Playwright MCP.
        if len(texte) < 4096 and (p := Path(texte)).is_file():
            try:
                return p.read_bytes()
            except OSError:
                return None
        # Sinon, du base64 — éventuellement préfixé d'une data-URL.
        if texte.startswith("data:"):
            texte = texte.split(",", 1)[-1]
        try:
            brut = base64.b64decode(texte, validate=True)
        except (binascii.Error, ValueError):
            return None
        return brut if brut.startswith(b"\x89PNG") else None

    return None


class ObservateurNavigateur:
    """Relie les événements d'outils Playwright à un sidecar ASCII.

    L'objet est passif par construction : `sur_outil()` reçoit le nom et le
    résultat d'un appel déjà exécuté, n'en modifie rien, et se contente de poser
    une demande d'aperçu. Il ne peut donc pas influencer ce que le modèle voit.
    """

    def __init__(self, *, reglages: Reglages | None = None):
        self._etat: dict = {}
        self._verrou = threading.Lock()
        self._suspendu = threading.Event()
        self._racine: Path | None = None
        self._dossier: Path | None = None
        self._page_ouverte = threading.Event()
        self.sidecar = SidecarAscii(
            self._capturer, etat=self._lire_etat,
            reglages=reglages or Reglages(etiquette="navigateur"),
            actif=self._page_regardable,
        )

    def _page_regardable(self) -> bool:
        """Y a-t-il quelque chose à capturer spontanément ?

        Vrai entre la première navigation réussie et la fermeture du navigateur.
        Sans ce garde, le battement demanderait des captures avant qu'aucune page
        n'existe — Playwright répondrait par une erreur à chaque seconde — et
        continuerait longtemps après la fin du build.
        """
        return self._page_ouverte.is_set() and not self._suspendu.is_set()

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def demarrer(self) -> None:
        self.sidecar.demarrer()

    def arreter(self) -> None:
        """Arrête le fil ET nettoie le répertoire de captures.

        Le PRD demande des captures éphémères : chacune est déjà supprimée après
        conversion, et ce nettoyage final rattrape celles qu'une interruption
        aurait laissées.
        """
        self.sidecar.arreter()
        if self._dossier is not None:
            shutil.rmtree(self._dossier, ignore_errors=True)

    def __enter__(self) -> "ObservateurNavigateur":
        self.demarrer()
        return self

    def __exit__(self, *_) -> None:
        self.arreter()

    def suspendre(self) -> None:
        """Empêche toute capture — pendant qu'un appel d'outil est en vol.

        Deux appels MCP simultanés sur la même session ne se corrompent pas, mais
        une capture prise au milieu d'un clic montre une page en transition. La
        suspension évite d'afficher un état qui n'a jamais existé.
        """
        self._suspendu.set()

    def reprendre(self) -> None:
        self._suspendu.clear()

    # ── Entrée : un appel d'outil vient de se terminer ─────────────────────────

    def sur_outil(self, nom: str, resultat=None) -> None:
        """À appeler APRÈS l'exécution d'un outil. Ne rend rien, ne lève rien."""
        try:
            if not nom.startswith(PREFIXE):
                return
            self._noter(nom, resultat)
            echoue = _a_echoue(resultat)
            if nom == f"{PREFIXE}browser_close":
                self._page_ouverte.clear()
            elif nom == f"{PREFIXE}browser_navigate" and not echoue:
                self._page_ouverte.set()
            if nom in ACTIONS_VISIBLES and not echoue:
                self.sidecar.demander(nom[len(PREFIXE):])
        except Exception:                                        # noqa: BLE001
            pass

    # ── Production d'une capture ──────────────────────────────────────────────

    def _capturer(self) -> bytes | None:
        """Demande une capture au serveur MCP, la lit, puis la supprime.

        C'est le seul appel que l'observateur émet, et il est en LECTURE : il ne
        navigue pas, ne clique pas, ne change pas la page. La distinction est ce
        qui permet de dire que l'aperçu ne pilote pas le navigateur.
        """
        if self._suspendu.is_set():
            return None
        outil = self._outil_de_capture()
        if outil is None:
            return None
        dossier = self._dossier_de_captures(outil)
        if dossier is None:
            return None

        cible = dossier / f"{uuid.uuid4().hex[:12]}.png"
        try:
            resultat = outil.invoke({"filename": str(cible), "type": "png"})
            if cible.is_file():
                return cible.read_bytes()
            return _png_depuis(resultat)
        except Exception:                                        # noqa: BLE001
            return None
        finally:
            cible.unlink(missing_ok=True)

    def _dossier_de_captures(self, outil) -> Path | None:
        """Un dossier où Playwright ACCEPTE d'écrire, découvert une seule fois.

        Playwright MCP n'écrit que sous ses « allowed roots » — mesuré :

            filename=/tmp/x.png  → File access denied: … is outside allowed roots.
                                   Allowed roots: /home/kaine/…/ai-agent
            filename=x.png       → écrit à la RACINE du dépôt de l'utilisateur

        Les deux sont inacceptables : le premier échoue, le second sème des PNG
        dans le projet. La racine est donc apprise en provoquant délibérément le
        refus une fois, puis les captures vont dans un sous-dossier caché qu'on
        supprime à l'arrêt.

        Deviner la racine avec `Path.cwd()` marcherait ici et casserait ailleurs :
        le serveur MCP a son propre répertoire de travail, fixé à son démarrage.
        Le message d'erreur, lui, dit la vérité.
        """
        if self._dossier is not None:
            return self._dossier
        try:
            refus = str(outil.invoke({"filename": "/axon-sonde-racine.png"}))
            trouve = re.search(r"[Aa]llowed roots:\s*([^\n\"]+)", refus)
            if not trouve:
                return None
            racine = Path(trouve.group(1).split(",")[0].strip())
            if not racine.is_dir():
                return None
            dossier = racine / ".axon-apercu"
            dossier.mkdir(parents=True, exist_ok=True)
            self._racine, self._dossier = racine, dossier
            return dossier
        except Exception:                                        # noqa: BLE001
            return None

    @staticmethod
    def _outil_de_capture():
        try:
            from src.mcp_client.runtime import mcp_runtime
            for t in mcp_runtime().tools:
                if t.name == CAPTURE:
                    return t
        except Exception:                                        # noqa: BLE001
            return None
        return None

    # ── État textuel, pour le repli ───────────────────────────────────────────

    def _noter(self, nom: str, resultat) -> None:
        """Retient le peu qu'on sait de la page, sans jamais en dépendre.

        Ce qu'un serveur MCP met dans ses réponses n'est pas un contrat : on y
        cherche une URL et un titre, et leur absence n'est pas un problème — le
        repli affichera « — ».
        """
        court = nom[len(PREFIXE):]
        with self._verrou:
            self._etat["action"] = court
            if court == "browser_navigate":
                self._etat["titre"] = "—"
            texte = resultat if isinstance(resultat, str) else str(resultat or "")
            for ligne in texte.splitlines()[:24]:
                nu = ligne.strip()
                if nu.lower().startswith(("- page url:", "page url:", "url:")):
                    self._etat["url"] = nu.split(":", 1)[-1].strip()
                elif nu.lower().startswith(("- page title:", "page title:", "title:")):
                    self._etat["titre"] = nu.split(":", 1)[-1].strip()
            if court == "browser_console_messages":
                self._etat["erreurs"] = texte.lower().count("error")

    def _lire_etat(self) -> dict:
        with self._verrou:
            return dict(self._etat)


def _a_echoue(resultat) -> bool:
    """Un échec ne mérite pas de capture : la page n'a pas bougé.

    Le PRD parle d'actions « réussies ». Sans ce filtre, un clic sur un sélecteur
    introuvable ferait quand même une capture — un aller-retour pour réafficher
    exactement la même image.
    """
    if isinstance(resultat, dict):
        return str(resultat.get("status", "")).lower() in ("error", "not_found")
    if isinstance(resultat, str):
        bas = resultat.lower()
        return bas.startswith("error") or "### result\nerror" in bas
    return False
