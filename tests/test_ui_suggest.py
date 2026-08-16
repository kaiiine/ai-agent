"""Suggestion de saisie (src/ui/suggest.py) — et surtout ses silences.

Une suggestion absente ne se voit nulle part, et c'est pourtant là que tient la
qualité : proposée trop souvent, elle devient un bruit qu'on cesse de lire. La
dernière section rejoue de vraies frappes, parce que Tab est disputée entre le
menu de complétion et la suggestion.
"""

from __future__ import annotations

import threading
import time

import pytest
from prompt_toolkit.document import Document

from src.ui.completer import at_query, completion_context
from src.ui.suggest import _FENETRE, HistorySuggest, meilleure_suite, scores

_PHRASE = "peux tu analyser le betting engine"


def _bourrage(n: int) -> list[str]:
    """Lignes d'historique qui ne partagent aucun préfixe avec les phrases testées."""
    return [f"remplissage numero {i}" for i in range(n)]


# ══ Les silences ═══════════════════════════════════════════════════════════════
def test_un_prefixe_trop_court_ne_propose_rien():
    """Sous trois caractères, presque tout l'historique correspond — la
    suggestion serait une devinette présentée comme une aide."""
    assert meilleure_suite("pe", [_PHRASE]) is None
    assert meilleure_suite("p", [_PHRASE]) is None


def test_un_gain_derisoire_ne_propose_rien():
    """Compléter « engin » en « engine » ne fait pas gagner une frappe, ça fait
    clignoter l'écran."""
    assert meilleure_suite("peux tu analyser le betting engi", [_PHRASE]) is None


def test_une_ligne_deja_entierement_tapee_ne_propose_rien():
    assert meilleure_suite(_PHRASE, [_PHRASE]) is None


def test_une_slash_commande_appartient_au_menu():
    """Le menu montre les descriptions ; la suggestion, non. Deux mécanismes sur
    la même touche rendraient Tab imprévisible."""
    assert meilleure_suite("/mcp res", ["/mcp restart blender"]) is None


def test_un_chemin_de_fichier_appartient_au_menu():
    assert meilleure_suite("regarde @src/ui/co",
                           ["regarde @src/ui/completer.py stp"]) is None


def test_une_saisie_multiligne_ne_propose_rien():
    """Le texte gris s'afficherait au milieu de ce qui est écrit."""
    assert meilleure_suite("peux tu\nanalyser", [_PHRASE + "\nanalyser tout"]) is None


def test_un_historique_vide_ne_propose_rien():
    assert meilleure_suite("peux tu", []) is None


def test_aucune_correspondance_ne_propose_rien():
    assert meilleure_suite("zzz inconnu", [_PHRASE]) is None


# ══ Ce qui est proposé ═════════════════════════════════════════════════════════
def test_la_suite_de_la_ligne_est_proposee():
    assert meilleure_suite("peux tu ana", [_PHRASE]) == "lyser le betting engine"


def test_la_casse_du_debut_est_ignoree_mais_la_suite_est_rendue_telle_quelle():
    """Taper une majuscule ne doit pas faire disparaître l'aide ; la suite, elle,
    reste celle qui a été réellement écrite."""
    assert meilleure_suite("Peux tu ana", [_PHRASE]) == "lyser le betting engine"


def test_la_suggestion_est_toujours_une_ligne_reellement_saisie():
    """Rien n'est fabriqué : `texte + suite` a existé tel quel dans l'historique."""
    historique = [_PHRASE, "peux tu analyser le hockey", "bonjour"]
    for debut in ("peux", "peux tu ana", "peux tu analyser le h"):
        suite = meilleure_suite(debut, historique)
        if suite is not None:
            assert debut + suite in historique


# ══ Le classement : habitude contre fraîcheur ══════════════════════════════════
def test_une_habitude_repetee_bat_une_frappe_unique_recente():
    """Trois emplois il y a une trentaine de tours pèsent plus qu'un seul emploi
    à l'instant — sinon la dernière phrase tapée écraserait toujours la
    formulation qu'on emploie sans arrêt."""
    historique = (["axon regarde la CLV du hockey"] * 3
                  + _bourrage(29)
                  + ["axon regarde la couverture du jour"])

    assert meilleure_suite("axon regarde la ", historique) == "CLV du hockey"


def test_une_frappe_recente_bat_une_habitude_oubliee():
    """Symétrique : passé une centaine de tours, une vieille habitude ne pèse
    plus rien. C'est ce qui permet de changer de façon d'écrire."""
    historique = (["axon regarde la couverture du jour"] * 3
                  + _bourrage(100)
                  + ["axon regarde la CLV du hockey"])

    assert meilleure_suite("axon regarde la ", historique) == "CLV du hockey"


def test_au_dela_de_la_fenetre_une_ligne_n_est_plus_proposee():
    """Une formulation d'il y a mille tours n'est plus la tienne, et la borne
    garde le coût par frappe constant."""
    historique = ["zzz formulation tres ancienne"] + _bourrage(_FENETRE + 100)

    assert meilleure_suite("zzz", historique) is None


def test_le_poids_decroit_strictement_avec_l_anciennete():
    poids = scores(["a", "b", "c"])
    assert poids["c"] > poids["b"] > poids["a"] > 0


# ══ L'adaptateur prompt_toolkit ════════════════════════════════════════════════
class _Historique:
    def __init__(self, lignes):
        self._lignes = lignes

    def get_strings(self):
        return self._lignes


class _Tampon:
    def __init__(self, historique):
        self.history = historique


def _suggestion(texte: str, lignes: list[str], curseur: int | None = None):
    document = Document(texte, cursor_position=curseur)
    resultat = HistorySuggest().get_suggestion(_Tampon(_Historique(lignes)), document)
    return None if resultat is None else resultat.text


def test_l_adaptateur_rend_la_suite():
    assert _suggestion("peux tu ana", [_PHRASE]) == "lyser le betting engine"


def test_rien_n_est_propose_quand_le_curseur_n_est_pas_en_fin_de_ligne():
    """Le texte gris s'insérerait visuellement au milieu de la phrase."""
    assert _suggestion("peux tu ana", [_PHRASE], curseur=4) is None


def test_un_historique_en_panne_ne_casse_pas_la_saisie():
    """Une suggestion est un confort ; elle ne doit jamais empêcher d'écrire."""
    class _Casse:
        def get_strings(self):
            raise OSError("disque illisible")

    document = Document("peux tu ana")
    assert HistorySuggest().get_suggestion(_Tampon(_Casse()), document) is None


# ══ Frontière partagée avec le menu de complétion ══════════════════════════════
@pytest.mark.parametrize("texte,attendu", [
    ("/mcp test",            True),
    ("@src/ui",              True),
    ("regarde @src/ui",      True),
    ("peux tu analyser",     False),
    ("mon mail a@b.fr",      False),   # un @ collé à un mot n'ouvre pas de menu
    ("@src/ui puis autre",   False),   # le fragment s'arrête au premier espace
])
def test_la_frontiere_est_celle_du_menu(texte, attendu):
    assert completion_context(texte) is attendu


def test_la_frontiere_est_la_meme_source_que_le_menu():
    """`completion_context` et le menu doivent se prononcer identiquement : une
    divergence rendrait Tab imprévisible sans qu'aucun test ne le voie."""
    from src.ui.completer import SlashCompleter

    for texte in ("@src", "regarde @src", "/mcp", "/", "bonjour", "a@b.fr"):
        via_menu = texte.startswith("/") or at_query(texte) is not None
        assert completion_context(texte) is via_menu
    # et le menu consomme bien ce qu'il revendique
    assert list(SlashCompleter().get_completions(Document("/mc"), None))


# ══ Intégration : la touche Tab, disputée entre les deux mécanismes ════════════
def _attendre(predicat, timeout: float = 5.0) -> None:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if predicat():
            return
        time.sleep(0.01)
    raise AssertionError("condition jamais atteinte")


def _saisir(frappes: list[tuple[str, str]], historique: list[str]) -> str:
    """Rejoue des frappes dans une session identique à celle du produit.

    Chaque frappe attend un ÉTAT plutôt qu'un délai : la suggestion et la
    complétion sont calculées par des tâches asynchrones, et un `sleep` fixe
    rendrait le test tantôt vert tantôt rouge selon la charge de la machine.
    """
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from src.ui.streaming import build_session

    memoire = InMemoryHistory()
    for ligne in historique:
        memoire.append_string(ligne)

    with create_pipe_input() as tuyau:
        session = build_session(history=memoire, input=tuyau, output=DummyOutput())

        def taper():
            _attendre(lambda: session.app.is_running)
            for texte, condition in frappes:
                tuyau.send_text(texte)
                tampon = session.app.current_buffer
                _attendre({
                    "suggestion": lambda: tampon.suggestion is not None,
                    "menu":       lambda: tampon.complete_state is not None,
                    "insere":     lambda: tampon.suggestion is None,
                }[condition])
            tuyau.send_text("\r")

        threading.Thread(target=taper, daemon=True).start()
        return session.prompt()


def test_tab_accepte_la_suggestion():
    assert _saisir([("peux tu", "suggestion"), ("\t", "insere")],
                   [_PHRASE, _PHRASE, "bonjour"]) == _PHRASE


def test_tab_complete_toujours_les_slash_commandes():
    """La retombée : quand la suggestion ne s'affiche pas, Tab reste le menu."""
    assert _saisir([("/mcp res", "menu"), ("\t", "menu")], [_PHRASE]) == "/mcp restart"


def test_sans_tab_rien_n_est_insere():
    """La suggestion est visible mais n'entre JAMAIS dans le message sans geste."""
    assert _saisir([("peux tu", "suggestion")], [_PHRASE, _PHRASE]) == "peux tu"
