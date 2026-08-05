"""Une coupure de flux ne doit pas coûter le tour entier.

`IncompleteRead(66316 bytes read, 256871 more expected)` : la connexion tombe en
cours de lecture de la réponse. Ce n'est ni un rate-limit, ni un dépassement de
contexte — les deux seules classes que la boucle savait traiter — donc l'erreur
remontait telle quelle et l'utilisateur perdait tout, y compris une réponse déjà
en partie produite.

Réémettre est SÛR : rien n'a été livré, aucun outil n'a pu s'exécuter. La requête
elle-même était valide, seul son transport a échoué.
"""

from __future__ import annotations

import inspect

import pytest

from src.orchestrator import graph as graph_module

SOURCE = inspect.getsource(graph_module)


def _marqueurs() -> tuple[str, ...]:
    """Les marqueurs sont locaux au corps de `_chat_node_factory` : on les lit
    depuis la source plutôt que d'exposer une constante juste pour le test."""
    debut = SOURCE.index("_TRANSIENT_MARKERS = (")
    fin = SOURCE.index(")", debut)
    bloc = SOURCE[debut:fin]
    return tuple(l.strip().strip('",') for l in bloc.splitlines()[1:] if l.strip())


@pytest.mark.parametrize("erreur", [
    "IncompleteRead(66316 bytes read, 256871 more expected)",
    "ChunkedEncodingError: response ended prematurely",
    "ProtocolError('Connection broken')",
    "ConnectionResetError: [Errno 104] Connection reset by peer",
    "RemoteDisconnected: Remote end closed connection without response",
    "ReadTimeout: HTTPSConnectionPool read timed out",
])
def test_les_coupures_de_flux_sont_reconnues(erreur):
    """Chaque forme rencontrée doit matcher, sinon elle reste fatale en silence."""
    err = f"{type(erreur).__name__}: {erreur}".lower()
    assert any(m in err for m in _marqueurs()), f"non reconnue : {erreur}"


@pytest.mark.parametrize("erreur", [
    "429 Too Many Requests",
    "context length exceeded",
    "invalid api key",
    "model not found",
])
def test_les_erreurs_non_transitoires_ne_sont_pas_reprises(erreur):
    """Réessayer une clé invalide ou un contexte trop long ne peut pas aboutir :
    ce serait masquer une panne réelle derrière des reprises inutiles."""
    err = erreur.lower()
    assert not any(m in err for m in _marqueurs()), f"reprise à tort : {erreur}"


def test_la_reprise_est_bornee():
    """Une reprise illimitée transformerait une panne durable en boucle muette."""
    assert "_MAX_TRANSIENT_RETRIES = 3" in SOURCE
    assert "transient_retries += 1" in SOURCE
    assert "if transient_retries <= _MAX_TRANSIENT_RETRIES:" in SOURCE


def test_l_erreur_est_classee_sur_le_TYPE_et_le_message():
    """`IncompleteRead` n'apparaît que dans le TYPE de l'exception : `str(e)` seul
    donne « (66316 bytes read, 256871 more expected) », sans le nom de la classe.
    Classer sur le message seul raterait donc précisément le cas rencontré."""
    assert 'err = f"{type(e).__name__}: {e}".lower()' in SOURCE


def test_la_reprise_precede_les_autres_classes_d_erreur():
    """Une coupure de flux dont le message contiendrait « timeout » ne doit pas
    être happée par la branche contexte, qui tronquerait les messages sans raison."""
    i_transient = SOURCE.index("_TRANSIENT_MARKERS)")
    i_ratelimit = SOURCE.index("_RATE_LIMIT_MARKERS)")
    assert i_transient < i_ratelimit
