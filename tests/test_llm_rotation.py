"""Toutes les clés sont essayées, sur tous les chemins.

Le pool existait, mais seuls l'orchestrateur et l'agent de code s'en servaient.
`/fiche`, `/exo` et `/letter` construisaient UN client et mouraient sur le
premier 429 — dix clés configurées, une seule jamais sollicitée.
"""

from __future__ import annotations

import pytest

from src.llm.rotation import clients, vaut_la_peine_de_reessayer


@pytest.fixture
def pool(monkeypatch):
    from src.llm import key_pool

    class _Pool:
        cles = {"ollama_cloud": ["o1", "o2"], "gemini": ["g1"], "mistral": ["m1"]}
        marquees: list = []

        def keys_for(self, p):
            return list(self.cles.get(p, []))

        def next_healthy(self, p):
            return (self.cles.get(p) or [""])[0]

        def mark_rate_limited(self, p, k):
            self.marquees.append(("quota", p, k))

        def mark_bad_key(self, p, k):
            self.marquees.append(("morte", p, k))

    instance = _Pool()
    instance.marquees = []
    monkeypatch.setattr(key_pool, "get_pool", lambda: instance)
    monkeypatch.setattr(key_pool, "get_fallback_order",
                        lambda: ["ollama_cloud", "gemini", "mistral"])
    return instance


def test_toutes_les_cles_du_backend_avant_les_replis(pool):
    ordre = [(f, c) for f, c, _ in clients("ollama_cloud", lambda p, k: (p, k))]

    assert ordre == [("ollama_cloud", "o1"), ("ollama_cloud", "o2"),
                     ("gemini", "g1"), ("mistral", "m1")]


def test_le_backend_choisi_passe_en_premier_meme_hors_ordre_de_repli(pool):
    premier = next(iter(clients("mistral", lambda p, k: (p, k))))

    assert premier[0] == "mistral"


def test_aucun_fournisseur_n_est_visite_deux_fois(pool):
    visites = [f for f, _, _ in clients("gemini", lambda p, k: None)]

    assert len(visites) == len(pool.cles["gemini"]) + 2 + 1
    assert visites.count("gemini") == 1


def test_le_client_est_construit_avec_sa_propre_cle(pool):
    construits = [c for _, _, c in clients("ollama_cloud", lambda p, k: f"{p}:{k}")]

    assert construits[:2] == ["ollama_cloud:o1", "ollama_cloud:o2"]


def test_le_changement_de_cle_est_annonce_mais_pas_le_premier(pool):
    """Annoncer la clé de départ ne dirait rien ; annoncer les suivantes, si."""
    vus: list = []
    list(clients("ollama_cloud", lambda p, k: None,
                 notifier=lambda p, k: vus.append((p, k))))

    assert ("ollama_cloud", "o1") not in vus
    assert ("ollama_cloud", "o2") in vus
    assert ("gemini", "g1") in vus


@pytest.mark.parametrize("message", [
    "429 you have reached your weekly usage limit",
    "RESOURCE_EXHAUSTED quota exceeded",
    "Unauthorized (status code: 401)",
    "rate limit reached",
])
def test_les_erreurs_de_cle_declenchent_un_nouvel_essai(message):
    assert vaut_la_peine_de_reessayer(RuntimeError(message))


@pytest.mark.parametrize("message", [
    "prompt trop long", "connection refused", "500 internal error",
])
def test_les_autres_erreurs_ne_font_pas_bruler_les_cles(message):
    """Réessayer une erreur qui n'a rien à voir gaspillerait dix clés."""
    assert not vaut_la_peine_de_reessayer(RuntimeError(message))


def test_une_cle_401_est_marquee_morte_pas_en_quota(pool):
    from src.llm.rotation import marquer_echec

    marquer_echec("ollama_cloud", "o1", RuntimeError("Unauthorized 401"))
    marquer_echec("ollama_cloud", "o2", RuntimeError("429 quota"))

    assert pool.marquees == [("morte", "ollama_cloud", "o1"),
                             ("quota", "ollama_cloud", "o2")]


@pytest.mark.parametrize("chemin,fabrique", [
    ("src/ui/streaming.py", "make_orchestrator_llm_with_key"),
    ("src/agents/study/tools.py", "make_orchestrator_llm_with_key"),
])
def test_les_chemins_directs_utilisent_la_rotation(chemin, fabrique):
    """`/fiche`, `/exo` et `/letter` n'héritent d'aucune reprise du graphe."""
    import pathlib

    source = pathlib.Path(chemin).read_text(encoding="utf-8")

    assert "from src.llm.rotation import" in source
    assert fabrique in source
