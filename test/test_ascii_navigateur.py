"""L'observateur Playwright : passif, et il faut le prouver.

Ce fichier tient les engagements du PRD qui portent sur le NAVIGATEUR, là où
`test_ascii_sidecar.py` tient ceux du moteur générique :

    ne pilote pas         seule la capture est émise, jamais une navigation
    ne modifie rien       le résultat d'outil ressort identique, à l'octet
    pas de boucle         sa propre capture ne déclenche pas de capture
    pas de gaspillage     une lecture ou un échec ne déclenche rien
    éphémère              aucun fichier de capture ne survit à la conversion
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ui.ascii.navigateur import (
    ACTIONS_VISIBLES, CAPTURE, LECTURES, PREFIXE, ObservateurNavigateur, _png_depuis,
)
from src.ui.ascii.sidecar import Reglages

_PETIT = Reglages(colonnes=8, lignes=4, intervalle_min=0.0)


@pytest.fixture
def observateur():
    """Démarré explicitement : sans `demarrer()`, une demande reste en attente et
    aucun fil ne la consomme. Ce n'est pas une subtilité de test mais le
    mécanisme qui rend l'aperçu désactivable — à `apercu_navigateur: False`,
    personne n'appelle `demarrer()` et il n'y a pas de fil du tout."""
    obs = ObservateurNavigateur(reglages=_PETIT)
    obs.demarrer()
    yield obs
    obs.arreter()


# ── Ce qui déclenche, et ce qui ne déclenche pas ───────────────────────────────
def test_sa_propre_capture_ne_declenche_pas_de_capture():
    """Le piège central : `browser_take_screenshot` EST un outil navigateur.
    Sans exclusion, observer sa propre capture en déclencherait une autre, à
    l'infini."""
    assert CAPTURE not in ACTIONS_VISIBLES
    assert CAPTURE in LECTURES


@pytest.mark.parametrize("outil", sorted(LECTURES))
def test_une_lecture_ne_declenche_aucune_capture(observateur, outil):
    """Lire la console ou l'arbre d'accessibilité ne change rien à l'écran :
    capturer coûterait un aller-retour pour réafficher la même image."""
    observateur.sur_outil(outil, "ok")

    assert observateur.sidecar.statistiques["rendus"] == 0


@pytest.mark.parametrize("outil", ["playwright__browser_navigate",
                                  "playwright__browser_click",
                                  "playwright__browser_fill_form"])
def test_une_action_visible_demande_un_apercu(observateur, outil):
    """On patche `_outil_de_capture`, pas `_capturer`.

    Le producteur est lié à la CONSTRUCTION du sidecar
    (`SidecarAscii(self._capturer, …)`), donc remplacer l'attribut après coup
    n'a aucun effet : le vrai `_capturer` tourne, démarre le runtime MCP, et un
    test unitaire se met à lancer des serveurs. `_outil_de_capture` est résolu à
    l'appel, lui.
    """
    with patch.object(ObservateurNavigateur, "_outil_de_capture",
                      staticmethod(lambda: None)):
        observateur.sur_outil(outil, "### Result\nOK")
        _attendre(lambda: observateur.sidecar.statistiques["rendus"] >= 1)

    assert observateur.sidecar.statistiques["rendus"] >= 1


def test_un_outil_non_navigateur_est_ignore(observateur):
    """Le sidecar navigateur ne réagit pas à un `shell_run` ou un `local_read_file`."""
    for outil in ("shell_run", "local_read_file", "blender__get_scene_info"):
        observateur.sur_outil(outil, "ok")

    assert observateur.sidecar.statistiques["rendus"] == 0


@pytest.mark.parametrize("resultat", [
    {"status": "error", "error": "sélecteur introuvable"},
    "Error: element not found",
    {"status": "not_found"},
])
def test_une_action_echouee_ne_declenche_rien(observateur, resultat):
    """Le PRD dit « actions réussies ». Un clic raté n'a pas bougé la page :
    capturer réafficherait exactement la même image."""
    observateur.sur_outil("playwright__browser_click", resultat)

    assert observateur.sidecar.statistiques["rendus"] == 0


def test_une_suspension_empeche_la_capture(observateur):
    """Une capture prise pendant un clic montre une page en transition — un état
    qui n'a jamais existé pour l'utilisateur."""
    observateur.suspendre()

    assert observateur._capturer() is None


# ── Il ne modifie jamais ce qu'il observe ─────────────────────────────────────
def test_le_resultat_d_outil_ressort_identique(observateur):
    """La contrainte la plus importante : l'observateur est branché sur le chemin
    des résultats d'outils. S'il en modifiait un, il changerait ce que le modèle
    lit — et cesserait d'être passif."""
    resultat = {"status": "ok", "url": "http://localhost:3000", "liste": [1, 2]}
    avant = repr(resultat)

    observateur.sur_outil("playwright__browser_navigate", resultat)

    assert repr(resultat) == avant


def test_sur_outil_ne_rend_rien(observateur):
    """Rien à réinjecter, donc rien qui puisse remonter au modèle par erreur."""
    assert observateur.sur_outil("playwright__browser_click", "ok") is None


def test_sur_outil_ne_leve_jamais(observateur):
    """Il est appelé depuis la boucle d'outils : une exception y ferait échouer
    le travail qu'il est censé simplement regarder."""
    class Hostile:
        def __str__(self):
            raise RuntimeError("je refuse d'être lu")

    observateur.sur_outil("playwright__browser_navigate", Hostile())
    observateur.sur_outil("playwright__browser_click", None)


# ── Extraction de la capture, quelle qu'en soit la forme ───────────────────────
def test_des_octets_png_sont_reconnus():
    assert _png_depuis(b"\x89PNG\r\n\x1a\nreste") == b"\x89PNG\r\n\x1a\nreste"


def test_un_chemin_de_fichier_est_lu(tmp_path):
    """La forme la plus courante côté Playwright MCP : il écrit et rend le chemin."""
    f = tmp_path / "capture.png"
    f.write_bytes(b"\x89PNG-contenu")

    assert _png_depuis(str(f)) == b"\x89PNG-contenu"


def test_du_base64_est_decode():
    import base64

    brut = b"\x89PNG\r\n\x1a\ndonnees"
    assert _png_depuis(base64.b64encode(brut).decode()) == brut


def test_une_data_url_est_decodee():
    import base64

    brut = b"\x89PNG\r\n\x1a\nx"
    url = "data:image/png;base64," + base64.b64encode(brut).decode()
    assert _png_depuis(url) == brut


def test_un_bloc_de_contenu_mcp_est_reconnu():
    import base64

    brut = b"\x89PNG\r\n\x1a\ny"
    blocs = [{"type": "text", "text": "capture prise"},
             {"type": "image", "data": base64.b64encode(brut).decode()}]
    assert _png_depuis(blocs) == brut


@pytest.mark.parametrize("entree", [
    None, "", "pas du base64 du tout !!", {"autre": "chose"}, [], 42,
    "aGVsbG8gd29ybGQ=",          # base64 valide, mais pas un PNG
])
def test_ce_qui_n_est_pas_une_capture_rend_none(entree):
    """Rendre `None` plutôt que de lever : le sidecar affichera l'état."""
    assert _png_depuis(entree) is None


# ── Éphémère ──────────────────────────────────────────────────────────────────
def test_la_capture_est_supprimee_apres_conversion(observateur, tmp_path):
    """Le PRD exige des captures éphémères. Le fichier NOUS appartient — nous en
    imposons le chemin — donc le supprimer est sûr."""
    ecrits: list[Path] = []

    def faux_outil_invoke(args):
        chemin = Path(args["filename"])
        chemin.write_bytes(b"\x89PNG-faux")
        ecrits.append(chemin)
        return str(chemin)

    outil = MagicMock()
    outil.invoke.side_effect = faux_outil_invoke
    observateur._dossier = tmp_path          # racine déjà découverte
    with patch.object(ObservateurNavigateur, "_outil_de_capture", staticmethod(lambda: outil)):
        png = observateur._capturer()

    assert png == b"\x89PNG-faux"
    assert ecrits and not ecrits[0].exists(), "la capture doit être supprimée"


def test_la_racine_autorisee_est_apprise_du_refus(observateur, tmp_path):
    """Playwright MCP n'écrit que sous ses « allowed roots ». Mesuré :
    `/tmp/x.png` est refusé, et un nom nu atterrit à la RACINE du dépôt de
    l'utilisateur. La racine est donc apprise en provoquant le refus une fois,
    plutôt que devinée avec `Path.cwd()` — le serveur MCP a son propre répertoire
    de travail, fixé à son démarrage."""
    outil = MagicMock()
    outil.invoke.return_value = (
        "### Error\nError: File access denied: /tmp/x.png is outside allowed "
        f"roots. Allowed roots: {tmp_path}")

    dossier = observateur._dossier_de_captures(outil)

    assert dossier == tmp_path / ".axon-apercu"
    assert dossier.is_dir()


def test_un_refus_illisible_ne_produit_aucune_capture(observateur):
    """Sans racine connue, écrire au hasard sèmerait des PNG chez l'utilisateur."""
    outil = MagicMock()
    outil.invoke.return_value = "### Error\nquelque chose d'inattendu"

    assert observateur._dossier_de_captures(outil) is None
    assert observateur._capturer() is None


def test_le_dossier_de_captures_disparait_a_l_arret(tmp_path):
    obs = ObservateurNavigateur(reglages=_PETIT)
    outil = MagicMock()
    outil.invoke.return_value = f"Allowed roots: {tmp_path}"
    dossier = obs._dossier_de_captures(outil)
    assert dossier.is_dir()

    obs.arreter()

    assert not dossier.exists()


def test_sans_serveur_mcp_la_capture_rend_none(observateur):
    """Aucun Playwright joignable : une vue d'état, pas une erreur."""
    with patch.object(ObservateurNavigateur, "_outil_de_capture", staticmethod(lambda: None)):
        assert observateur._capturer() is None


# ── État textuel ──────────────────────────────────────────────────────────────
def test_l_url_et_le_titre_sont_retenus(observateur):
    observateur.sur_outil("playwright__browser_navigate",
                          "- Page URL: http://localhost:3000\n- Page Title: Accueil")

    etat = observateur._lire_etat()
    assert etat["url"] == "http://localhost:3000"
    assert etat["titre"] == "Accueil"


def test_les_erreurs_de_console_sont_comptees(observateur):
    observateur.sur_outil("playwright__browser_console_messages",
                          "[ERROR] boom\n[error] encore\n[LOG] ok")

    assert observateur._lire_etat()["erreurs"] == 2


def test_un_resultat_sans_url_ne_pose_pas_de_probleme(observateur):
    """Ce qu'un serveur MCP met dans ses réponses n'est pas un contrat."""
    observateur.sur_outil("playwright__browser_click", "Clicked on button")

    assert observateur._lire_etat()["action"] == "browser_click"


def _attendre(condition, delai: float = 2.0) -> None:
    import time

    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return
        time.sleep(0.02)
    pytest.fail("condition non atteinte dans le délai")
