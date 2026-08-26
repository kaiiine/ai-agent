"""Les clients servent le MÊME protocole — c'est tout l'intérêt de l'exercice.

Le HITL vivait dans `src/ui/streaming.py`, en six mécanismes. Conséquence
mesurée : `src/api/streaming.py` n'en connaissait aucun, et une question posée
via l'API ne trouvait personne. Ce que ces tests gardent, ce n'est pas le rendu
— c'est le fait que la LECTURE de la demande soit commune.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.orchestrator.hitl import Demande, Question


def _instantane(valeur):
    """Un état de graphe factice portant une interruption."""
    return SimpleNamespace(tasks=(SimpleNamespace(
        interrupts=(SimpleNamespace(value=valeur),)),))


class _Graphe:
    def __init__(self, instantane):
        self._i = instantane

    def get_state(self, config):
        return self._i


def test_le_TUI_lit_la_demande_dans_l_etat_du_graphe():
    from src.ui.streaming import _demande_du_graphe

    demande = Demande(genre="autorisation", cle="rm -rf /tmp/x",
                      apercu="Fichier : /tmp/x",
                      questions=(Question("Exécuter ?", ("Non", "Oui"), affirmatif="Oui"),))
    lue = _demande_du_graphe(_Graphe(_instantane(demande.en_clair())), {})

    assert lue == demande, "le TUI ne reconstruit pas fidèlement la demande"


def test_un_graphe_sans_interruption_ne_rend_rien():
    from src.ui.streaming import _demande_du_graphe

    assert _demande_du_graphe(_Graphe(SimpleNamespace(tasks=())), {}) is None


def test_un_graphe_injoignable_ne_casse_pas_le_tour():
    """Un `get_state` qui lève ne doit pas faire tomber la session : au pire on
    ne voit pas la demande, et le tour se termine normalement."""
    from src.ui.streaming import _demande_du_graphe

    class _Cassé:
        def get_state(self, config):
            raise RuntimeError("indisponible")

    assert _demande_du_graphe(_Cassé(), {}) is None


def test_une_panne_d_affichage_ne_vaut_pas_accord(monkeypatch):
    """Le point qui compte pour la sécurité. Si le questionnaire échoue, on rend
    des réponses VIDES — lues comme un refus. Rendre une valeur par défaut, ou
    laisser l'exception filer et reprendre plus tard, produirait un accord que
    personne n'a donné."""
    from src.orchestrator.hitl import accorde
    from src.ui import review

    monkeypatch.setattr(review, "ask_user_questions",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("terminal perdu")))

    question = Question("Exécuter ?", ("Non", "Oui"), affirmatif="Oui")
    reponses = review.servir_demande(Demande(
        genre="autorisation", cle="rm -rf /", questions=(question,)))

    assert reponses == [""]
    assert not accorde(reponses[0], question)


def test_les_reponses_sont_rendues_DANS_L_ORDRE_des_questions(monkeypatch):
    """`ask_user_questions` rend un dict indexé par le texte ; le graphe attend
    l'ordre. Les confondre décalerait les réponses d'une question — silencieux,
    et faux."""
    from src.ui import review

    monkeypatch.setattr(review, "ask_user_questions",
                        lambda posees: {"Deuxième ?": "B", "Première ?": "A"})

    reponses = review.servir_demande(Demande(
        genre="clarification", cle="x",
        questions=(Question("Première ?"), Question("Deuxième ?"))))

    assert reponses == ["A", "B"]


def test_une_reponse_absente_devient_du_vide(monkeypatch):
    from src.ui import review

    monkeypatch.setattr(review, "ask_user_questions", lambda posees: {})
    reponses = review.servir_demande(Demande(
        genre="clarification", cle="x",
        questions=(Question("A ?"), Question("B ?"))))
    assert reponses == ["", ""]


# ── Le client API ────────────────────────────────────────────────────────────
def test_l_API_lit_la_meme_demande_que_le_TUI():
    """Le motif entier du chantier. `src/api/streaming.py` ne connaissait AUCUN
    des six mécanismes de HITL : une question posée par le graphe n'y trouvait
    personne, et la commande qu'elle gardait n'était jamais autorisée."""
    from src.api.streaming import _demande_en_attente
    from src.ui.streaming import _demande_du_graphe

    demande = Demande(genre="autorisation", cle="rm -rf /tmp/x",
                      questions=(Question("Exécuter ?", ("Non", "Oui"), affirmatif="Oui"),))
    graphe = _Graphe(_instantane(demande.en_clair()))

    assert _demande_en_attente(graphe, {}) == _demande_du_graphe(graphe, {}) == demande


def test_l_API_rend_la_demande_en_texte_avec_ses_choix():
    """Une API de chat n'a pas de canal interactif : la question devient un TOUR.
    Elle doit donc dire ce qu'on attend, sinon le client répond à côté."""
    from src.api.streaming import _rendre_demande

    texte = _rendre_demande(Demande(
        genre="autorisation", cle="rm -rf /tmp/x",
        apercu="Fichier : /tmp/x",
        questions=(Question("Commande DESTRUCTIVE :\n\nrm -rf /tmp/x",
                            ("Non, annuler", "Oui, exécuter"),
                            affirmatif="Oui, exécuter"),)))

    assert "Fichier : /tmp/x" in texte, "l'aperçu doit être montré"
    assert "rm -rf /tmp/x" in texte
    assert "Non, annuler" in texte and "Oui, exécuter" in texte, (
        "sans les choix, le client ne peut pas répondre par le bon libellé")


def test_un_fil_en_attente_traite_le_message_comme_une_REPONSE():
    """Le piège de ce transport. Un fil qui attend ne recommence pas un tour :
    réinjecter le message comme une nouvelle question relancerait le graphe
    depuis le début, et la demande resterait en attente pour toujours."""
    import inspect

    from src.api import streaming

    source = inspect.getsource(streaming.stream_orchestrator)
    position_test = source.index("_demande_en_attente(orchestrator, config) is not None")
    position_etat = source.index('state = {"messages"')
    assert position_test < position_etat, (
        "l'état neuf est construit avant d'avoir vérifié qu'on n'attend pas une réponse")
