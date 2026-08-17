"""Un échec d'outil ne doit pas emporter la clé avec lui.

`tool_error_to_message` est branché comme `handle_tool_errors` du `ToolNode`,
donc TOUTE exception d'outil devient un résultat lu par le modèle. Or les
exceptions de `requests` embarquent l'URL complète, paramètres compris. Mesuré
avant correction :

    message → …Max retries exceeded with url: /v4/matches?apiKey=CLE_SECRETE_ABC123
    la clé y figure → True

La destination fait la gravité : le contexte du modèle, donc le fournisseur LLM,
un tiers. Le second chemin — `_log_failure` → `failure_log` — écrit sur disque
un journal qui comptait déjà 3757 entrées.

La rédaction est appliquée TOUJOURS ici, alors que `redactor.should_redact()` ne
la réserve qu'aux backends cloud. C'est voulu : ce garde-là protège des RÉSULTATS
d'outils, où masquer pourrait détruire ce que l'utilisateur a demandé à lire. Un
message d'erreur n'a pas ce besoin.
"""
import json

import pytest

from src.orchestrator.resilience import _message_sur, tool_error_to_message


def _message(exc: Exception) -> str:
    return json.loads(tool_error_to_message(exc))["message"]


# ── Le cas mesuré ─────────────────────────────────────────────────────────────
def test_une_cle_dans_une_url_ne_part_pas_au_modele():
    """La forme exacte relevée : une clé en query string, dans l'exception que
    `requests` lève quand l'appel échoue."""
    exc = RuntimeError(
        "HTTPSConnectionPool(host='api.football-data.org', port=443): "
        "Max retries exceeded with url: /v4/matches?apiKey=CLE_SECRETE_ABC123")

    rendu = _message(exc)

    assert "CLE_SECRETE_ABC123" not in rendu
    assert "apiKey=***" in rendu
    assert "api.football-data.org" in rendu, "l'hôte reste utile au diagnostic"


def test_une_vraie_exception_reseau_est_nettoyee():
    """Non simulée : on provoque l'échec pour que le test porte sur ce que
    `requests` produit réellement, pas sur ce qu'on croit qu'il produit."""
    import requests

    with pytest.raises(Exception) as capture:
        requests.get("https://exemple.invalide/v1?apiKey=SECRET_REEL_123456",
                     timeout=0.001)

    assert "SECRET_REEL_123456" not in _message(capture.value)


@pytest.mark.parametrize("brut, secret", [
    ("auth failed for key sk-proj-ABCDEF123456", "sk-proj-ABCDEF123456"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdefghij", "eyJhbGciOiJIUzI1NiJ9abcdefghij"),
    ("x-apisports-key: 9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c", "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c"),
    ("GOOGLE_API_KEY=AIzaSyDxxxxxxxxxxxxxxxxxxxxxxxx", "AIzaSyDxxxxxxxxxxxxxxxxxxxxxxxx"),
    ("?token=abc123def456&page=2", "abc123def456"),
])
def test_les_formes_de_secret_rencontrees_sont_masquees(brut, secret):
    """`x-apisports-key` est dans cette liste parce qu'il PASSAIT intact : le
    motif exigeait `api` collé à `key`, et c'est l'en-tête que
    `stats_aggregator` envoie."""
    assert secret not in _message(RuntimeError(brut))


# ── Ce qui doit survivre ──────────────────────────────────────────────────────
def test_un_message_sans_secret_reste_intact():
    """Masquer trop rendrait les erreurs inutiles au modèle, qui doit pouvoir
    expliquer ce qui a échoué."""
    brut = "Connection refused: localhost:3000 is not responding"

    assert _message(RuntimeError(brut)) == brut


@pytest.mark.parametrize("brut", [
    "keyboard: azertyuiop",
    "monkey: bananes",
    "status: ok",
    "FileNotFoundError: /home/kaine/projets/rapport.md",
])
def test_ce_qui_ressemble_a_un_secret_sans_l_etre_survit(brut):
    assert _message(RuntimeError(brut)) == brut


def test_une_exception_sans_message_reste_lisible():
    assert _message(RuntimeError()) == "échec sans message"


def test_le_type_d_erreur_et_la_consigne_restent():
    """Le modèle doit savoir que c'est un ÉCHEC, pas un résultat — c'est la
    raison d'être de ce module."""
    charge = json.loads(tool_error_to_message(TimeoutError("trop long")))

    assert charge["status"] == "TOOL_ERROR"
    assert charge["error_type"] == "TimeoutError"
    assert "N'invente jamais" in charge["note"]


# ── L'interruption de LangGraph n'est pas une erreur ──────────────────────────
def test_une_interruption_de_graphe_est_relevee():
    """`GraphBubbleUp` porte `interrupt()` et les confirmations utilisateur.
    L'avaler bloquerait les validations — la rédaction ne doit pas changer ça."""
    from langgraph.errors import GraphBubbleUp

    with pytest.raises(GraphBubbleUp):
        tool_error_to_message(GraphBubbleUp())


# ── Le journal sur disque passe par le même filtre ────────────────────────────
def test_le_journal_des_echecs_ne_recoit_pas_le_secret(tmp_path, monkeypatch):
    """Second chemin, moins visible : `_log_failure` écrit `message[:300]` dans
    ~/.axon/backend_failures.jsonl, un fichier qu'on relit et qu'on partage
    parfois pour diagnostiquer."""
    import src.infra.failure_log as journal
    from src.orchestrator.resilience import _log_failure

    fichier = tmp_path / "failures.jsonl"
    monkeypatch.setattr(journal, "LOG_PATH", fichier)

    _log_failure("groq", RuntimeError("auth failed key=SECRET_DU_JOURNAL_99"),
                 "retry", False)

    contenu = fichier.read_text()
    assert "SECRET_DU_JOURNAL_99" not in contenu
    assert "groq" in contenu, "le backend reste consigné, c'est l'objet du journal"


def test_le_journal_ne_casse_jamais_le_tour(monkeypatch):
    """Un journal qui lève serait exactement le défaut que ce module corrige."""
    import src.infra.failure_log as journal
    from src.orchestrator.resilience import _log_failure

    def _explose(**_):
        raise OSError("disque plein")

    monkeypatch.setattr(journal, "record", _explose)
    _log_failure("groq", RuntimeError("peu importe"), "retry", False)


def test_la_redaction_ne_depend_pas_du_backend():
    """`redactor.should_redact()` ne vaut que pour les backends cloud. Un message
    d'erreur n'a jamais besoin du secret pour informer, donc il est masqué même en
    local — sinon la protection dépendrait d'un réglage.

    La garantie est STRUCTURELLE et se lit sur la signature : `_message_sur` ne
    reçoit pas de backend, donc il ne peut pas en dépendre. Une version antérieure
    de ce test cherchait « should_redact » dans le source et tombait sur la
    docstring qui explique justement la distinction.
    """
    import inspect

    from src.orchestrator import resilience

    parametres = inspect.signature(resilience._message_sur).parameters
    assert list(parametres) == ["exc"], (
        "aucun réglage ne doit pouvoir désactiver la rédaction d'un message d'erreur")
