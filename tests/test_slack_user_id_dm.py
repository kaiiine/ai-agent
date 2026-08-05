"""Envoyer un message à une PERSONNE dont on a l'identifiant Slack.

`slack_find_user` rend un identifiant d'utilisateur (`U…`). `_resolve_channel` le
traitait comme un identifiant de conversation et le passait tel quel à
`chat.postMessage`, qui répondait « Canal ou utilisateur introuvable ».

Le chemin le plus naturel pour le modèle — chercher la personne, puis lui écrire —
était donc le seul à ne pas fonctionner, alors que la branche `@nom` faisait déjà
le bon appel juste en dessous.
"""

from __future__ import annotations

import pytest

from src.agents.slack import tools as slack_tools


class _FauxClient:
    """Enregistre les appels pour prouver QUEL chemin a été pris."""

    def __init__(self):
        self.ouvertures: list[str] = []

    def conversations_open(self, users: str):
        self.ouvertures.append(users)
        return {"channel": {"id": "D_OUVERT"}}


@pytest.fixture(autouse=True)
def _cache_vierge():
    """Le cache est un dict de module : sans reset, un test contamine le suivant."""
    slack_tools._CHANNEL_CACHE.clear()
    slack_tools._MEMBERS_CACHE = []
    yield
    slack_tools._CHANNEL_CACHE.clear()
    slack_tools._MEMBERS_CACHE = []


@pytest.mark.parametrize("user_id", ["U06KZGGL403", "W012ENTERPRISE"])
def test_un_identifiant_utilisateur_ouvre_une_conversation_directe(user_id):
    """`U…` (et `W…` sur Enterprise Grid) désignent des PERSONNES, pas des canaux."""
    client = _FauxClient()

    resolu = slack_tools._resolve_channel(client, user_id)

    assert resolu == "D_OUVERT"
    assert client.ouvertures == [user_id], "conversations_open n'a pas été appelé"


@pytest.mark.parametrize("conversation_id", ["C123CANAL", "D456DM", "G789GROUPE"])
def test_un_identifiant_de_conversation_passe_tel_quel(conversation_id):
    """Ouvrir une conversation déjà identifiée serait un appel réseau inutile."""
    client = _FauxClient()

    assert slack_tools._resolve_channel(client, conversation_id) == conversation_id
    assert client.ouvertures == []


def test_la_conversation_ouverte_est_mise_en_cache():
    """Un envoi par lot ne doit pas rouvrir la même conversation à chaque message."""
    client = _FauxClient()

    slack_tools._resolve_channel(client, "U06KZGGL403")
    slack_tools._resolve_channel(client, "U06KZGGL403")

    assert client.ouvertures == ["U06KZGGL403"], "conversation rouverte inutilement"


def test_les_deux_chemins_vers_une_personne_donnent_la_meme_conversation():
    """`@nom` et `U…` désignent la même personne : ils doivent converger, sinon le
    comportement dépend de la façon dont le modèle a formulé sa demande."""
    client = _FauxClient()

    par_id = slack_tools._resolve_channel(client, "U06KZGGL403")

    slack_tools._CHANNEL_CACHE.clear()
    client_bis = _FauxClient()
    # `users_list` est PAGINÉ : le vrai client rend un itérable de réponses.
    client_bis.users_list = lambda **kw: [{"members": [
        {"id": "U06KZGGL403", "real_name": "Nicolas Danquigny",
         "name": "nicolas.danquigny", "deleted": False, "is_bot": False,
         "profile": {"display_name": "Nicolas"}},
    ]}]
    par_nom = slack_tools._resolve_channel(client_bis, "@nicolas.danquigny")

    assert par_id == par_nom == "D_OUVERT"
