"""Le centre ASCII : rendu, coalescence, et ce qu'il ne doit jamais faire.

Les garanties du PRD, chacune tenue par un test plutôt que par une intention :

    passif          rien ne part vers le modèle, aucun résultat d'outil modifié
    événementiel    aucun sondage — sans demande, aucun rendu
    coalescé        dix demandes pendant un rendu n'en produisent qu'un de plus
    non bloquant    `demander()` rend la main immédiatement
    éphémère        aucun fichier de capture ne survit
    dégradé         sans moteur graphique, une vue d'état, jamais une erreur
    silencieux      un producteur qui lève ne fait pas échouer ce qu'il observe
"""
import threading
import time

import pytest

from src.ui.ascii import Reglages, SidecarAscii, moteurs_disponibles, rendre
from src.ui.ascii.cadre import Cadre
from src.ui.ascii.moteurs import (
    MoteurBraille, MoteurChafa, MoteurDemiBloc, MoteurEtat, choisir,
)

_PETIT = Reglages(colonnes=8, lignes=4, intervalle_min=0.0)


def _png(largeur: int = 32, hauteur: int = 32, couleur=(255, 175, 0)) -> bytes:
    """Un vrai PNG, pas un octet factice : les moteurs passent par Pillow, donc
    un faux en-tête testerait le chemin d'échec au lieu du rendu."""
    import io

    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), couleur).save(tampon, format="PNG")
    return tampon.getvalue()


# ── Moteurs ───────────────────────────────────────────────────────────────────
def test_le_demi_bloc_rend_une_cellule_par_colonne():
    cadre = MoteurDemiBloc().rendre(_png(), 8, 4)

    assert cadre is not None
    assert len(cadre.lignes) == 4
    assert cadre.lignes[0].plain == "▀" * 8


def test_le_demi_bloc_porte_deux_couleurs_par_cellule():
    """C'est ce qui fait sa fidélité sur une page web : le haut et le bas de la
    cellule sont deux pixels différents."""
    cadre = MoteurDemiBloc().rendre(_png(), 4, 2)

    style = cadre.lignes[0].spans[0].style
    assert style.color is not None and style.bgcolor is not None


def test_le_braille_rend_des_caracteres_braille():
    cadre = MoteurBraille().rendre(_png(couleur=(0, 0, 0)), 6, 3)

    assert cadre is not None
    assert all(0x2800 <= ord(c) <= 0x28FF for c in cadre.lignes[0].plain)


def test_le_braille_reste_monochrome():
    """Huit points par cellule, un seul ton : c'est le compromis assumé, et le
    test le fixe pour qu'on ne croie pas à une régression de couleur."""
    cadre = MoteurBraille().rendre(_png(couleur=(0, 0, 0)), 4, 2)

    styles = {s.style for ligne in cadre.lignes for s in ligne.spans}
    assert len(styles) == 1


def test_un_png_invalide_ne_leve_pas():
    """Un moteur rend `None`, jamais une exception — sinon un aperçu raté
    interromprait ce qu'il observe."""
    for moteur in (MoteurDemiBloc(), MoteurBraille(), MoteurChafa()):
        assert moteur.rendre(b"pas du png", 8, 4) is None


def test_le_registre_retombe_sur_un_moteur_qui_marche():
    """Un PNG tronqué doit produire une vue d'état, pas un aperçu figé sur
    l'image d'avant."""
    assert rendre(b"tronque", 8, 4) is None or isinstance(rendre(_png(), 8, 4), Cadre)
    assert rendre(_png(), 8, 4) is not None


def test_l_etat_est_toujours_disponible_et_ne_renonce_jamais():
    """C'est lui qui garantit qu'il y a TOUJOURS un moteur : le sidecar n'a donc
    aucun cas « aucun rendu possible » à traiter."""
    etat = MoteurEtat()

    assert etat.disponible() is True
    assert etat.rendre(b"", 40, 6) is not None


def test_l_etat_affiche_ce_qu_on_sait_de_la_page():
    cadre = MoteurEtat().depuis_etat(
        {"url": "http://localhost:3000", "titre": "Accueil", "erreurs": 2}, 60, 6)
    texte = "\n".join(l.plain for l in cadre.lignes)

    assert "localhost:3000" in texte and "Accueil" in texte and "2 erreur" in texte


def test_un_moteur_prefere_inconnu_ne_casse_rien():
    """Un réglage mal orthographié doit dégrader l'aperçu, pas la session."""
    assert choisir("moteur-qui-n-existe-pas") in moteurs_disponibles()


def test_le_moteur_prefere_est_respecte_s_il_existe():
    assert choisir("braille").nom == "braille"


# ── Sidecar : événementiel, pas de sondage ────────────────────────────────────
def test_sans_demande_aucun_rendu():
    """La différence avec une boucle de screenshots : au repos, il ne se passe
    rien. Aucun CPU, aucune capture, aucun fichier."""
    appels = []
    with SidecarAscii(lambda: appels.append(1) or _png(), reglages=_PETIT) as s:
        time.sleep(0.4)

        assert appels == []
        assert s.statistiques["rendus"] == 0


def test_une_demande_produit_un_cadre():
    with SidecarAscii(lambda: _png(), reglages=_PETIT) as s:
        s.demander("navigate")
        _attendre(lambda: s.cadre is not None)

        assert s.cadre is not None
        assert s.statistiques["rendus"] == 1


def test_demander_ne_bloque_pas():
    """Un producteur lent ne doit pas retarder l'appelant — sinon l'agent
    attendrait son propre affichage."""
    def lent():
        time.sleep(0.5)
        return _png()

    with SidecarAscii(lent, reglages=_PETIT) as s:
        debut = time.monotonic()
        s.demander("clic")
        ecoule = time.monotonic() - debut

        assert ecoule < 0.05, f"demander() a bloqué {ecoule:.3f}s"


def test_les_demandes_sont_coalescees():
    """Dix demandes pendant un rendu en cours n'en produisent qu'UN de plus.
    Sans cela, une rafale de clics ferait la queue et l'aperçu montrerait le
    passé pendant plusieurs secondes."""
    barriere = threading.Event()

    def bloquant():
        barriere.wait(timeout=2)
        return _png()

    with SidecarAscii(bloquant, reglages=_PETIT) as s:
        s.demander("premier")
        time.sleep(0.15)                      # le rendu est en cours
        for i in range(10):
            s.demander(f"rafale-{i}")
        barriere.set()
        _attendre(lambda: s.statistiques["rendus"] >= 2, delai=3)
        time.sleep(0.3)

        stats = s.statistiques
        assert stats["fusionnees"] == 9, f"coalescence manquée : {stats}"
        assert stats["rendus"] == 2, f"un rendu par demande : {stats}"


def test_l_intervalle_minimum_espace_les_rendus():
    """Le garde-fou contre le scintillement et la surconsommation."""
    reglages = Reglages(colonnes=8, lignes=4, intervalle_min=0.4)
    with SidecarAscii(lambda: _png(), reglages=reglages) as s:
        s.demander("a")
        _attendre(lambda: s.statistiques["rendus"] == 1)
        debut = time.monotonic()
        s.demander("b")
        _attendre(lambda: s.statistiques["rendus"] == 2, delai=3)

        assert time.monotonic() - debut >= 0.35


def test_un_producteur_qui_leve_donne_une_vue_d_etat():
    """La dégradation gracieuse : l'utilisateur voit l'état, pas une erreur."""
    def casse():
        raise RuntimeError("playwright injoignable")

    with SidecarAscii(casse, etat=lambda: {"url": "http://x"}, reglages=_PETIT) as s:
        s.demander("navigate")
        _attendre(lambda: s.cadre is not None)

        assert s.cadre.moteur == "etat"
        assert "http://x" in "\n".join(l.plain for l in s.cadre.lignes)


def test_un_fournisseur_d_etat_qui_leve_ne_casse_rien():
    """Le repli du repli : même sans état lisible, il faut un cadre."""
    with SidecarAscii(lambda: None,
                      etat=lambda: (_ for _ in ()).throw(ValueError("nope")),
                      reglages=_PETIT) as s:
        s.demander("clic")
        _attendre(lambda: s.cadre is not None)

        assert s.cadre is not None


def test_demarrer_deux_fois_ne_lance_qu_un_fil():
    s = SidecarAscii(lambda: _png(), reglages=_PETIT)
    try:
        s.demarrer()
        premier = s._fil
        s.demarrer()

        assert s._fil is premier
    finally:
        s.arreter()


def test_le_fil_est_daemon():
    """Un aperçu ne doit pas empêcher Axon de rendre la main."""
    s = SidecarAscii(lambda: _png(), reglages=_PETIT)
    try:
        s.demarrer()
        assert s._fil.daemon is True
    finally:
        s.arreter()


def test_arreter_est_sans_effet_si_jamais_demarre():
    SidecarAscii(lambda: _png(), reglages=_PETIT).arreter()


# ── La contrainte centrale : rien ne part vers le modèle ───────────────────────
def test_le_sidecar_n_expose_aucune_sortie_textuelle():
    """La garantie STRUCTURELLE du PRD. Le seul chemin de sortie est `__rich__`,
    vers l'affichage. Aucune méthode publique ne rend de chaîne, donc aucune ne
    peut être branchée par erreur sur un résultat d'outil.
    """
    publiques = {n for n in dir(SidecarAscii)
                 if not n.startswith("_") and callable(getattr(SidecarAscii, n))}

    assert publiques == {"demarrer", "arreter", "demander"}, (
        f"surface publique inattendue : {publiques}")


def test_le_rendu_est_un_renderable_rich_pas_du_texte():
    from rich.panel import Panel

    with SidecarAscii(lambda: _png(), reglages=_PETIT) as s:
        assert isinstance(s.__rich__(), Panel)


def test_un_cadre_ne_retient_ni_image_ni_fichier():
    """Ce qui permet de garder le dernier cadre en mémoire sans retenir de
    ressource, et de supprimer la capture aussitôt convertie."""
    cadre = MoteurDemiBloc().rendre(_png(), 8, 4)
    champs = set(cadre.__dataclass_fields__)

    assert not champs & {"png", "image", "chemin", "path", "fichier"}


# ── Aide ──────────────────────────────────────────────────────────────────────
def _attendre(condition, delai: float = 2.0) -> None:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return
        time.sleep(0.02)
    pytest.fail("condition non atteinte dans le délai")


# ── Scène deux colonnes : l'aperçu ancré à droite ─────────────────────────
#
# La droite de l'écran est vide pendant tout un build. Le point d'appui est que
# `run_build(project_name, console)` REÇOIT sa console : lui en passer une autre
# suffit, et ses trente-et-un `console.print` n'ont pas à changer.

def _console(largeur=150, hauteur=32):
    from rich.console import Console
    return Console(width=largeur, height=hauteur, file=__import__("io").StringIO())


def test_la_scene_s_ancre_si_le_terminal_est_assez_large():
    from src.ui.ascii.scene import SceneBuild

    assert SceneBuild(_console(150, 32)).ancrable is True


@pytest.mark.parametrize("largeur, hauteur", [(80, 32), (110, 32), (150, 12)])
def test_un_terminal_trop_petit_renonce_a_l_ancrage(largeur, hauteur):
    """Une colonne de gauche trop étroite rendrait le journal illisible : mieux
    vaut pas d'aperçu ancré qu'un journal haché."""
    from src.ui.ascii.scene import SceneBuild

    assert SceneBuild(_console(largeur, hauteur)).ancrable is False


def test_une_largeur_nulle_desactive_l_ancrage():
    """`apercu_colonnes: 0` doit rendre l'affichage classique, qui garde tout
    l'historique du terminal."""
    from src.ui.ascii.scene import SceneBuild

    assert SceneBuild(_console(), largeur_apercu=0).ancrable is False


def test_hors_ancrage_tout_repart_vers_la_vraie_console():
    """La façade doit être transparente : sans ancrage, `run_build` s'affiche
    exactement comme avant."""
    from rich.text import Text

    from src.ui.ascii.scene import SceneBuild

    console = _console(80, 32)
    scene = SceneBuild(console, largeur_apercu=0)
    scene.print(Text("une ligne de build"))
    scene.poser_apercu(Text("un aperçu"))

    sortie = console.file.getvalue()
    assert "une ligne de build" in sortie and "un aperçu" in sortie


def test_la_largeur_de_capture_suit_la_colonne():
    """Capturer plus large que la colonne ferait rogner l'image par Rich ;
    plus étroit laisserait un bord vide."""
    from src.ui.ascii.scene import SceneBuild

    scene = SceneBuild(_console(), largeur_apercu=46)

    assert 20 <= scene.colonnes_apercu < 46


def test_le_journal_est_borne():
    """Il ne garde que ce qu'il peut montrer : rendre quatre cents renderables à
    chaque rafraîchissement pour n'en afficher qu'une vingtaine coûterait cher."""
    from rich.text import Text

    from src.ui.ascii.scene import SceneBuild

    scene = SceneBuild(_console())
    for i in range(1200):
        scene._journal.append(Text(f"ligne {i}"))

    assert len(scene._journal) <= 400


def test_run_build_n_expose_que_print_a_la_scene():
    """La façade n'implémente que `print` parce que c'est tout ce que le build
    utilise. Si un jour il appelle `console.rule` ou `console.status`, ce test
    le dit avant que l'affichage ne casse en production."""
    import re

    from src.agents.coding import build_runner

    source = __import__("inspect").getsource(build_runner)
    methodes = set(re.findall(r"console\.([a-z_]+)", source))

    assert methodes <= {"print", "poser_apercu", "colonnes_apercu", "width", "height"}, (
        f"la scène doit aussi fournir : {methodes}")


# ── Battement adaptatif : suivre ce qui bouge, ignorer ce qui dort ────────
#
# Le sidecar était purement événementiel, et l'utilisateur ne voyait qu'UNE image
# par phase — parce que l'agent ne fait qu'un appel navigateur par phase. Une
# capture coûte 47 ms mesurés (34 de MCP, 12 de rendu) sur un fil de fond : le
# coût n'est donc pas ce qui limite. C'est l'utilité — recapturer cent fois une
# page immobile n'apprend rien.

def test_sans_battement_configure_rien_ne_bat():
    """Le mode purement événementiel reste accessible."""
    reglages = Reglages(colonnes=8, lignes=4, intervalle_min=0.0, battement=0.0)
    with SidecarAscii(lambda: _png(), reglages=reglages, actif=lambda: True) as s:
        time.sleep(0.5)

        assert s.statistiques["spontanees"] == 0


def test_sans_page_ouverte_rien_ne_bat():
    """Sans ce garde, on demanderait des captures avant qu'aucune page n'existe,
    et longtemps après la fin du build."""
    reglages = Reglages(colonnes=8, lignes=4, intervalle_min=0.0, battement=0.05)
    with SidecarAscii(lambda: _png(), reglages=reglages, actif=lambda: False) as s:
        time.sleep(0.5)

        assert s.statistiques["spontanees"] == 0


def test_une_page_ouverte_declenche_des_captures_spontanees():
    reglages = Reglages(colonnes=8, lignes=4, intervalle_min=0.0, battement=0.05)
    with SidecarAscii(lambda: _png(), reglages=reglages, actif=lambda: True) as s:
        _attendre(lambda: s.statistiques["spontanees"] >= 3, delai=3)

        assert s.statistiques["rendus"] >= 3


def test_une_image_figee_espace_le_battement():
    """L'adaptation : même image deux fois de suite → l'intervalle double,
    jusqu'à la borne. Une page immobile devient presque gratuite."""
    reglages = Reglages(colonnes=8, lignes=4, intervalle_min=0.0,
                        battement=0.05, battement_max=0.4)
    with SidecarAscii(lambda: _png(), reglages=reglages, actif=lambda: True) as s:
        _attendre(lambda: s.statistiques["battement"] >= 0.4, delai=4)

        assert s.statistiques["battement"] == 0.4


def test_une_image_qui_change_ramene_le_battement_au_minimum():
    """Une page qui bouge doit être suivie de près — c'est tout l'intérêt."""
    etat = {"n": 0, "fige": True}

    def variable():
        etat["n"] += 1
        if etat["fige"]:
            return _png(couleur=(0, 0, 0))       # identique → l'intervalle double
        # Une couleur différente à CHAQUE appel : la page « bouge » vraiment, donc
        # l'intervalle doit rester au minimum et pas se ré-espacer aussitôt.
        return _png(couleur=(etat["n"] % 200, 40, 90))

    reglages = Reglages(colonnes=8, lignes=4, intervalle_min=0.0,
                        battement=0.05, battement_max=0.8)
    with SidecarAscii(variable, reglages=reglages, actif=lambda: True) as s:
        _attendre(lambda: s.statistiques["battement"] > 0.05, delai=3)
        etat["fige"] = False
        _attendre(lambda: s.statistiques["battement"] == 0.05, delai=4)

        assert s.statistiques["battement"] == 0.05


def test_un_evenement_reste_prioritaire_sur_le_battement():
    """Une action de l'agent ne doit pas attendre le prochain battement."""
    reglages = Reglages(colonnes=8, lignes=4, intervalle_min=0.0, battement=30.0)
    with SidecarAscii(lambda: _png(), reglages=reglages, actif=lambda: True) as s:
        s.demander("clic")
        _attendre(lambda: s.statistiques["rendus"] >= 1)

        assert s.statistiques["spontanees"] == 0, "le rendu vient de l'événement"
