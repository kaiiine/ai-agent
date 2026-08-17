"""La saisie multi-ligne : aller à la ligne sans envoyer, envoyer sans casser.

La session était en une seule ligne : Entrée envoyait, et AUCUNE touche ne
pouvait insérer un retour. Passer `multiline=True` inverse le rôle d'Entrée — par
défaut elle irait à la ligne et plus rien n'enverrait — donc les liaisons ci-
dessous ne sont pas un confort, elles rétablissent le geste attendu.

Sur Maj+Entrée, une limite qu'il faut connaître : prompt_toolkit 3.0.52 ne la
connaît pas. `enter` est un alias de `c-m` et l'énumération des touches n'a
aucune variante shift pour elle — `s-tab` et `s-left` existent, rien pour entrée.
La cause est en amont : la plupart des terminaux envoient le même octet `\\r` pour
les deux. D'où trois chemins, testés séparément ici.

Les frappes sont rejouées sur une VRAIE session, celle du produit, via un tuyau
d'entrée — pas sur une reconstitution des liaisons.
"""
import threading
import time

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput


def _saisir(frappes: str) -> str:
    """Rejoue des frappes sur la session réelle et rend ce qu'elle a validé."""
    from prompt_toolkit.history import InMemoryHistory

    from src.ui.streaming import build_session

    with create_pipe_input() as tuyau:
        session = build_session(history=InMemoryHistory(),
                                input=tuyau, output=DummyOutput())

        def taper():
            fin = time.monotonic() + 3
            while time.monotonic() < fin and not session.app.is_running:
                time.sleep(0.01)
            tuyau.send_text(frappes)

        threading.Thread(target=taper, daemon=True).start()
        return session.prompt()


# ── Envoyer ───────────────────────────────────────────────────────────────────
def test_entree_envoie():
    """Le geste le plus courant ne doit surtout pas changer."""
    assert _saisir("bonjour\r") == "bonjour"


def test_entree_envoie_meme_apres_plusieurs_lignes():
    assert _saisir("a\nb\nc\r") == "a\nb\nc"


# ── Aller à la ligne ──────────────────────────────────────────────────────────
def test_ctrl_j_va_a_la_ligne():
    """Le chemin universel : tout terminal émet Ctrl+J distinctement."""
    assert _saisir("une\nligne\r") == "une\nligne"


def test_alt_entree_va_a_la_ligne():
    """Le second chemin universel — Escape puis Entrée."""
    assert _saisir("une\x1b\rdeux\r") == "une\ndeux"


def test_maj_entree_va_a_la_ligne_en_protocole_kitty():
    """`ESC [ 13 ; 2 u` est ce qu'émettent kitty, ghostty, WezTerm et foot quand
    le protocole clavier est actif. Ailleurs la séquence n'arrive jamais et la
    liaison dort — c'est pourquoi elle ne suffit pas seule."""
    assert _saisir("une\x1b[13;2udeux\r") == "une\ndeux"


# ── Ce que l'envoi ne doit pas casser ─────────────────────────────────────────
def test_une_commande_slash_survit_au_multi_ligne():
    """`stream_once` teste `startswith('/')` : une commande suivie de détails sur
    plusieurs lignes doit rester reconnue comme une commande."""
    saisi = _saisir("/build axon-landing\navec le thème sombre\r")

    assert saisi.startswith("/build")
    assert "\n" in saisi


def test_le_texte_multi_ligne_traverse_le_nettoyage_de_stream_once():
    """`stream_once` fait `.strip()` : il retire les blancs de bord, jamais les
    retours internes. Sans ce test, remplacer `.strip()` par un nettoyage plus
    zélé écraserait silencieusement la mise en forme de l'utilisateur."""
    saisi = _saisir("  premier\ndeuxième  \r")

    assert saisi.strip() == "premier\ndeuxième"


@pytest.mark.parametrize("frappes, attendu", [
    ("\r", ""),                                   # entrée seule
    ("\n\r", "\n"),                               # une ligne vide puis envoi
    ("texte\n\r", "texte\n"),                     # retour final conservé
])
def test_les_saisies_limites_ne_plantent_pas(frappes, attendu):
    """Une saisie vide ou ne contenant qu'un retour doit rendre la main
    proprement : `stream_once` s'en occupe ensuite avec `if not user_message`."""
    assert _saisir(frappes) == attendu


# ── La complétion garde la priorité sur l'envoi ───────────────────────────────
def test_la_session_est_bien_multiligne():
    """La garantie structurelle : sans `multiline`, aucune touche ne peut
    insérer un retour, quelles que soient les liaisons."""
    from prompt_toolkit.history import InMemoryHistory

    from src.ui.streaming import build_session

    with create_pipe_input() as tuyau:
        session = build_session(history=InMemoryHistory(),
                                input=tuyau, output=DummyOutput())

        assert session.multiline is True


def test_entree_ne_traite_aucun_cas_particulier_de_completion():
    """La correction d'une erreur que j'avais introduite, et qui bloquait tout.

    Entrée validait d'abord la complétion ouverte, pour éviter qu'elle n'envoie
    au lieu d'insérer `/build`. Mais dans prompt_toolkit, Tab INSÈRE déjà la
    complétion dans le tampon tout en laissant `current_completion` renseigné :
    la condition ne distinguait pas « en attente » de « déjà écrite », Entrée la
    réappliquait, et la saisie ne se terminait JAMAIS. Le symptôme était un
    pytest sans fin, pas un échec — deux tests de `test_ui_suggest.py` restaient
    suspendus, et c'est un `timeout` qui l'a révélé.

    Le comportement, lui, est vérifié de bout en bout par
    `test_tab_complete_toujours_les_slash_commandes`, qui tape `/mcp res`, Tab,
    puis Entrée et attend « /mcp restart ». Ce test-ci garde la CAUSE.
    """
    import inspect

    from src.ui import streaming

    source = inspect.getsource(streaming._make_keybindings)

    assert "apply_completion" not in source, (
        "Entrée ne doit pas réappliquer une complétion que Tab a déjà insérée")
