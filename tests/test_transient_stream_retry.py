"""Classification des erreurs d'appel LLM.

`IncompleteRead(66316 bytes read, 256871 more expected)` : la connexion tombe en
cours de lecture. Ce n'est ni un rate-limit ni un dépassement de contexte — les
deux seules classes que la boucle savait traiter — donc l'erreur remontait telle
quelle et l'utilisateur perdait tout son tour, réponse comprise.

Ces tests portent sur `classify()`, qui décide de la stratégie. Ils ont d'abord
été écrits en cherchant des chaînes dans le source de `graph.py`, faute de
pouvoir atteindre la fonction ; son extraction dans `invocation.py` permet enfin
de l'appeler directement.
"""

from __future__ import annotations

import pytest

from src.orchestrator.invocation import MAX_TRANSIENT_RETRIES, classify


@pytest.mark.parametrize("exc", [
    Exception("IncompleteRead(66316 bytes read, 256871 more expected)"),
    Exception("ChunkedEncodingError: response ended prematurely"),
    Exception("ProtocolError('Connection broken')"),
    ConnectionResetError("[Errno 104] Connection reset by peer"),
    Exception("RemoteDisconnected: Remote end closed connection"),
    TimeoutError("read timed out"),
])
def test_les_coupures_de_flux_sont_transitoires(exc):
    assert classify(exc) == "transient"


def test_la_classification_lit_le_TYPE_autant_que_le_message():
    """`IncompleteRead` n'apparaît QUE dans le nom de la classe : `str(e)` seul
    donne « (66316 bytes read, …) », sans de quoi le reconnaître. Classer sur le
    message aurait raté précisément le cas rencontré."""
    class IncompleteRead(Exception):
        pass

    assert classify(IncompleteRead("(66316 bytes read, 256871 more expected)")) == "transient"


@pytest.mark.parametrize("exc,attendu", [
    (Exception("429 Too Many Requests"), "rate_limit"),
    (Exception("Resource has been exhausted (e.g. check quota)"), "rate_limit"),
    (Exception("context length exceeded"), "context"),
    (Exception("maximum token limit reached"), "context"),
    (Exception("invalid api key"), "unknown"),
    (Exception("model 'x' not found"), "unknown"),
    (Exception("400 INVALID_ARGUMENT: items missing field"), "unknown"),
])
def test_les_autres_familles_sont_distinguees(exc, attendu):
    """Chaque famille appelle une stratégie différente : les confondre revient à
    appliquer un remède qui ne peut pas marcher, puis à conclure à une panne."""
    assert classify(exc) == attendu


def test_le_429_de_gemini_est_reconnu():
    """`ResourceExhausted` ne contient PAS « resource_exhausted » (le nom de
    classe est collé) : c'est « 429 » dans le message qui sauve le cas."""
    class ResourceExhausted(Exception):
        pass

    assert classify(ResourceExhausted("429 Resource has been exhausted.")) == "rate_limit"


def test_la_reprise_transitoire_est_bornee():
    """Une reprise illimitée transformerait une panne durable en boucle muette."""
    assert 1 <= MAX_TRANSIENT_RETRIES <= 5


def test_les_interruptions_utilisateur_ne_sont_pas_des_exceptions():
    """`KeyboardInterrupt` et `SystemExit` ne dérivent pas d'`Exception` : aucune
    stratégie ne peut donc les avaler, et Ctrl-C reste possible."""
    assert not issubclass(KeyboardInterrupt, Exception)
    assert not issubclass(SystemExit, Exception)
