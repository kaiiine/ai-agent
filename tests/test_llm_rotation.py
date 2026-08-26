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


# ── Classification des erreurs ───────────────────────────────────────────────
#
# Un quota par MINUTE n'a ni le code ni le vocabulaire d'un quota par requête.
# Groq rend le sien en 413, sans « 429 » nulle part :
#
#   Error code: 413 — Request too large for model `qwen/qwen3.6-27b` ... on
#   tokens per minute (TPM): Limit 8000, Requested 16927 ... 'code':
#   'rate_limit_exceeded'
#
# Il tombait dans `_CONTEXTE`, parce que « token » figure dans « tokens per
# minute ». Classé comme une requête trop longue, donc jugé non réessayable :
# ni rotation de clé, ni repli de fournisseur. Le tour mourait sur un dump brut
# du fournisseur, alors que six clés `ollama_cloud` attendaient derrière.
#
# La cause tenait à un séparateur : `rate_limit_exceeded` ne matchait ni
# « rate limit » ni « ratelimit », l'underscore tombant entre les deux.

_413_TPM = (
    "Error code: 413 - {'error': {'message': 'Request too large for model "
    "`qwen/qwen3.6-27b` in organization `org_01` service tier `on_demand` on "
    "tokens per minute (TPM): Limit 8000, Requested 16927, please reduce your "
    "message size and try again.', 'type': 'tokens', 'code': "
    "'rate_limit_exceeded'}}"
)


@pytest.mark.parametrize("message, attendu", [
    (_413_TPM, "quota"),
    # Les trois graphies de la même notion. Aucune ne doit dépendre du séparateur.
    ("Error code: 429 - rate limit exceeded", "quota"),
    ("Error: rate_limit_exceeded", "quota"),
    ("RateLimitError: too many requests", "quota"),
    ("resource_exhausted: quota exceeded for this project", "quota"),
    # Une vraie erreur de longueur reste une erreur de longueur : le correctif
    # ne doit pas transformer tout ce qui contient « token » en quota.
    ("This model's maximum context length is 8192 tokens, "
     "however you requested 9000 tokens", "contexte"),
    ("401 Unauthorized: invalid_api_key", "cle_morte"),
    ("Error code: 503 - service unavailable", "serveur"),
])
def test_une_erreur_est_classee_par_sa_NATURE_pas_par_son_code(message, attendu):
    from src.llm.rotation import classer_erreur

    assert classer_erreur(Exception(message)) == attendu


def test_un_quota_par_minute_declenche_le_repli():
    """Le point entier : sans ça, six clés de repli restaient inutilisées."""
    from src.llm.rotation import vaut_la_peine_de_reessayer

    assert vaut_la_peine_de_reessayer(Exception(_413_TPM))


def test_une_requete_trop_longue_ne_declenche_PAS_le_repli():
    """L'inverse compte autant : changer de clé ne raccourcit pas un message.
    Réessayer huit fois la même requête trop longue ne fait que perdre huit
    allers-retours avant d'échouer pareil."""
    from src.llm.rotation import vaut_la_peine_de_reessayer

    assert not vaut_la_peine_de_reessayer(Exception(
        "This model's maximum context length is 8192 tokens, "
        "however you requested 9000 tokens"))


def test_le_separateur_ne_change_pas_la_classification():
    """La règle générale, énoncée à part de ses exemples : c'est elle qui évitera
    le prochain fournisseur qui écrira la notion d'une quatrième façon."""
    from src.llm.rotation import classer_erreur

    formes = ["rate limit", "rate_limit", "rate-limit", "RATE_LIMIT"]
    classes = {classer_erreur(Exception(f"Error: {f} exceeded")) for f in formes}
    assert classes == {"quota"}, f"classifications divergentes : {classes}"
