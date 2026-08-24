"""Une panne serveur se réessaie ; elle ne tue pas le tour.

Vécu, en plein nettoyage disque :

    erreur : Internal Server Error (ref: 31d9307d-…) (status code: -1)

Le tour était perdu, avec l'erreur brute à l'écran. Or `classify()` rangeait ce
cas dans `unknown`, dont l'échelle est faite pour « le provider REFUSE notre
requête » — modèle retiré, schéma d'outil invalide. Elle fait tourner les clés,
puis retire les outils. Aucun de ces remèdes ne répare une panne serveur, et le
second dégrade le tour pour rien.

Un 500 est pourtant de la même nature qu'une coupure de flux, déjà traitée :
le serveur a échoué APRÈS avoir accepté, rien n'a été livré, aucun outil n'a pu
s'exécuter. Réémettre est sûr — c'est le raisonnement que le module tenait déjà
pour `IncompleteRead`, et il vaut mot pour mot ici.

Une seule chose change : la CLASSIFICATION. J'avais aussi voulu faire basculer
les réessais épuisés sur l'échelle dégradée ; un test existant l'a refusé, à
raison — cette échelle retire les outils, et répondre sans outils à « supprime
ces fichiers » produit un texte plausible au lieu d'une action.
"""
import pytest

from src.orchestrator.invocation import MAX_TRANSIENT_RETRIES, classify


@pytest.mark.parametrize("message", [
    "Internal Server Error (ref: 31d9307d-8967-4426-aae8-e12f9550e199) (status code: -1)",
    "HTTP 500 Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "504 Gateway Timeout",
    "overloaded_error: the model is overloaded",
])
def test_une_panne_serveur_est_passagere(message):
    """Le serveur a accepté puis échoué : réémettre est sûr et suffisant."""
    assert classify(Exception(message)) == "transient"


def test_le_message_exact_de_l_incident():
    """Celui qui a tué le tour, mot pour mot."""
    exc = Exception("Internal Server Error (ref: 31d9307d-8967-4426-aae8-e12f9550e199) "
                    "(status code: -1)")

    assert classify(exc) == "transient"


# ── Les autres classes ne bougent pas ─────────────────────────────────────────
@pytest.mark.parametrize("message, attendu", [
    ("429 Too Many Requests", "rate_limit"),
    ("quota exceeded", "rate_limit"),
    ("maximum context length exceeded", "context"),
    ("IncompleteRead(66316 bytes read)", "transient"),
    ("connection reset by peer", "transient"),
    ("ValueError: argument invalide", "unknown"),
])
def test_les_autres_classes_restent_intactes(message, attendu):
    """Élargir `transient` ne doit pas avaler ce qui appelait un autre remède :
    un rate-limit veut une clé, un contexte trop long veut une compression."""
    assert classify(Exception(message)) == attendu


def test_une_erreur_de_code_reste_inconnue():
    """Réessayer un bug de programmation trois fois ne le répare pas — et
    masquerait la cause derrière un délai."""
    assert classify(TypeError("can only concatenate str")) == "unknown"


# ── L'échelle ne renonce plus trop tôt ────────────────────────────────────────
def test_les_reessais_epuises_renoncent_franchement():
    """J'avais d'abord fait basculer les réessais épuisés sur l'échelle dégradée.
    Un test existant l'a refusé, et il avait raison : cette échelle finit par
    RETIRER LES OUTILS, et répondre sans outils à « supprime ces fichiers »
    produit un texte plausible au lieu d'une action.

    Face à un réseau qui reste coupé, une erreur franche vaut mieux qu'une
    réponse qui fait semblant. Le correctif utile était la classification, pas
    l'obstination.
    """
    import inspect

    from src.orchestrator import invocation

    source = inspect.getsource(invocation.invoke_with_recovery)
    # On borne au bloc `transient` lui-même — jusqu'au `continue` qui le clôt —
    # plutôt qu'à un nombre de caractères : un commentaire ajouté décalerait la
    # fenêtre et ferait tomber le test sans que le code ait changé. C'est
    # exactement ce qui vient de m'arriver.
    debut = source.index('if genre == "transient"')
    bloc = source[debut:source.index("continue", debut)]

    assert "raise" in bloc


def test_le_plafond_de_reessais_reste_borne():
    """Sans borne, une panne durable boucle au lieu de rendre la main."""
    assert 1 <= MAX_TRANSIENT_RETRIES <= 5
