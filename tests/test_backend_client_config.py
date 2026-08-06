"""Configuration réseau des clients LLM.

Aucun client n'avait de timeout explicite, et leurs défauts divergent :

    Gemini    timeout=None      -> attente INFINIE
    Ollama    aucun champ       -> attente INFINIE
    Mistral   timeout=120       -> le seul borné
    Mistral   streaming=False   -> le seul à ne pas streamer

Deux symptômes vécus s'expliquent par là : « Gemini ne répond pas et ça bloque »
(pas de timeout) et « Mistral bugue une fois sur deux » (pas de streaming, donc
la réponse entière doit tenir dans une fenêtre de 120 s).

Ces tests fixent la configuration effective, celle que le client porte réellement
après construction — pas la présence d'un mot-clé dans le code.
"""

from __future__ import annotations

import pytest

from src.llm import models


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Clés factices : on construit les clients sans jamais appeler le réseau."""
    monkeypatch.setattr(models.settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(models.settings, "mistral_api_key", "test-key", raising=False)


# ── timeouts ────────────────────────────────────────────────────────────────────
def test_gemini_a_un_timeout_explicite():
    """Le défaut est `None` : une requête qui n'aboutit pas restait suspendue
    indéfiniment, et l'utilisateur n'avait plus qu'à tuer le processus."""
    llm = models.make_orchestrator_llm_with_key("gemini", "k")
    assert llm.timeout == models._REQUEST_TIMEOUT


def test_mistral_a_un_timeout_explicite():
    llm = models.make_orchestrator_llm_with_key("mistral", "k")
    assert llm.timeout == models._REQUEST_TIMEOUT


def test_ollama_porte_son_timeout_par_le_client_http():
    """`ChatOllama` n'expose pas de champ `timeout` : il passe par `client_kwargs`,
    transmis à httpx. Sans lui, aucune borne."""
    llm = models.make_orchestrator_llm_with_key("ollama_cloud", "k")
    assert llm.client_kwargs.get("timeout") == models._REQUEST_TIMEOUT


@pytest.mark.parametrize("provider", ["gemini", "mistral"])
def test_le_coding_a_aussi_ses_timeouts(provider):
    """Le specialist tourne plus longtemps que l'orchestrateur : c'est là qu'une
    attente infinie coûte le plus cher."""
    llm = models.make_coding_llm_with_key(provider, "k")
    assert llm.timeout == models._REQUEST_TIMEOUT


# ── streaming ───────────────────────────────────────────────────────────────────
def test_mistral_stream_comme_les_autres():
    """`ChatMistralAI` a `streaming=False` par défaut — seul de tous les clients.
    Sans streaming, l'interface reste sur « thinking » jusqu'au dernier octet, et
    toute la réponse doit tenir dans un seul délai."""
    assert models.make_orchestrator_llm_with_key("mistral", "k").streaming is True
    assert models.make_llm_mistral().streaming is True


# ── reprises internes ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("provider", ["gemini", "mistral"])
def test_les_reprises_internes_sont_courtes(provider):
    """Défauts : Gemini 6, Mistral 5, chacune avec son backoff. Sur un rate-limit
    annoncé à deux minutes, six reprises bloquent le tour d'autant — c'est ce
    temps mort qui est perçu comme un plantage. Axon a un pool de clés : basculer
    aboutit plus souvent qu'attendre la même clé."""
    llm = models.make_orchestrator_llm_with_key(provider, "k")
    assert llm.max_retries == models._CLIENT_MAX_RETRIES <= 2


# ── contexte Ollama ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("factory,args", [
    (models.make_llm, ()),
    (models.make_llm_ollama_cloud, ()),
])
def test_ollama_declare_son_contexte(factory, args):
    """`num_ctx=None` laisse le serveur choisir, et il choisit petit : les
    messages anciens sont tronqués côté serveur, sans erreur ni trace. Le local le
    posait déjà, le cloud l'avait oublié."""
    assert factory(*args).num_ctx == models._OLLAMA_NUM_CTX


def test_ollama_cloud_garde_son_contexte_sur_tous_les_chemins(monkeypatch):
    """Trois chemins mènent au client cloud (pool, clé unique, dernier recours) :
    un seul qui oublie `num_ctx` suffit à tronquer selon la façon dont la clé a
    été trouvée."""
    monkeypatch.setattr(models.settings, "ollama_api_key", "k", raising=False)
    monkeypatch.setattr("src.llm.key_pool.get_pool",
                        lambda: (_ for _ in ()).throw(RuntimeError("pool absent")))

    llm = models.make_llm_ollama_cloud()
    assert llm.num_ctx == models._OLLAMA_NUM_CTX
    assert llm.client_kwargs.get("timeout") == models._REQUEST_TIMEOUT


# ── clés transmises explicitement ───────────────────────────────────────────────
def test_mistral_recoit_sa_cle_meme_hors_pool():
    """Les chemins de repli s'en remettaient à la variable d'environnement, alors
    que le chemin Gemini équivalent passait la clé. Une configuration qui marche
    par un chemin et pas par l'autre est un piège."""
    llm = models.make_llm_mistral()
    assert llm.mistral_api_key is not None
