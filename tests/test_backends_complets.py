"""Un backend déclaré doit être câblé PARTOUT, sinon il échoue en silence.

Vécu sur NVIDIA : le chemin nominal marchait — `_chat_node_factory` appelait bien
`make_llm_nvidia` — mais les trois fabriques par CLÉ n'avaient pas de branche
`nvidia` et tombaient dans leur `else`. Conséquences mesurées, avec pourtant la
clé chargée dans le pool :

    make_coding_llm()                    → ChatOllama · minimax-m3:cloud
    make_orchestrator_llm_with_key(...)  → ChatOllama (repli ollama_cloud)

Rien ne plantait, rien ne prévenait. On croyait travailler sur NVIDIA, on payait
Ollama Cloud, et toute mesure portait sur un autre modèle que celui testé. Le
specialist de code n'aurait JAMAIS utilisé NVIDIA, et la rotation aurait basculé
sur Ollama au premier 429 — rendant `NVIDIA_API_KEYS` multi-clés inopérant.

Ces tests parcourent `_BACKENDS`, la liste qui fait foi : ils couvriront donc
d'eux-mêmes le prochain backend ajouté.
"""
from __future__ import annotations

import pytest

from src.ui.commands import _BACKENDS

#: Backends servis par une API distante — ceux dont une branche manquante se
#: traduit par un repli silencieux vers un AUTRE fournisseur. `ollama` local
#: n'utilise pas de clé et suit un chemin propre.
_CLOUD = [b for b in _BACKENDS if b != "ollama"]

#: Ce qu'on attend comme classe de client, par fournisseur. Vérifier la classe
#: et pas seulement l'absence d'exception est le cœur du test : le bug d'origine
#: rendait un client parfaitement valide — d'un autre fournisseur.
_CLASSE_ATTENDUE = {
    "groq": "ChatGroq",
    "gemini": "ChatGoogleGenerativeAI",
    "mistral": "ChatMistralAI",
    "nvidia": "ChatNVIDIA",
    "ollama_cloud": "ChatOllama",
}


@pytest.mark.parametrize("backend", _CLOUD)
def test_chaque_backend_a_sa_branche_dans_les_fabriques_par_cle(backend):
    """Le test qui aurait attrapé le bug. Une branche absente ne lève rien : elle
    rend le client d'un autre fournisseur."""
    from src.llm import models

    for fabrique in (models.make_orchestrator_llm_with_key,
                     models.make_coding_llm_with_key):
        client = fabrique(backend, "cle-de-test")
        attendu = _CLASSE_ATTENDUE.get(backend)
        assert attendu is not None, f"{backend} absent de _CLASSE_ATTENDUE"
        assert type(client).__name__ == attendu, (
            f"{fabrique.__name__}({backend!r}) rend un {type(client).__name__} "
            f"au lieu d'un {attendu} — repli silencieux vers un autre fournisseur")


@pytest.mark.parametrize("backend", _CLOUD)
def test_le_specialist_de_code_suit_le_backend_actif(backend):
    """`make_coding_llm()` lit `settings.llm_backend`. Sans branche dédiée, il
    retombait sur le `else` commenté « ollama_cloud »."""
    import src.infra.settings as reglages
    from src.llm import models

    precedent = reglages.settings.llm_backend
    try:
        reglages.settings.llm_backend = backend
        client = models.make_coding_llm()
        assert type(client).__name__ == _CLASSE_ATTENDUE[backend], (
            f"llm_backend={backend!r} donne un {type(client).__name__} — "
            f"le specialist travaillerait chez un autre fournisseur")
    finally:
        reglages.settings.llm_backend = precedent


@pytest.mark.parametrize("table, module", [
    ("_CONTEXT_LIMITS", "src.orchestrator.context"),
    ("_BACKEND_POLICY", "src.orchestrator.context"),
])
def test_chaque_backend_declare_sa_fenetre_et_sa_politique(table, module):
    """Ces tables se rabattent proprement sur un défaut — donc rien ne casse,
    et c'est précisément pourquoi un oubli y passe inaperçu jusqu'à ce que la
    compression se déclenche au mauvais moment."""
    import importlib

    valeurs = getattr(importlib.import_module(module), table)
    manquants = [b for b in _BACKENDS if b not in valeurs]
    assert not manquants, f"{table} ne connaît pas : {', '.join(manquants)}"


def test_le_budget_du_specialist_couvre_chaque_backend():
    from src.agents.coding.specialist import _CONTEXT_CHAR_BUDGET

    manquants = [b for b in _BACKENDS if b not in _CONTEXT_CHAR_BUDGET and b != "ollama"]
    assert not manquants, f"budget de contexte absent pour : {', '.join(manquants)}"


def test_le_decoupage_en_phases_couvre_chaque_backend():
    from src.llm.prompts.decomposeur import BUDGET_PAR_BACKEND

    manquants = [b for b in _BACKENDS if b not in BUDGET_PAR_BACKEND]
    assert not manquants, f"budget de phases /build absent pour : {', '.join(manquants)}"


def test_le_backend_actif_est_toujours_essaye_avant_les_replis():
    """Ce qui rend l'absence de `nvidia` dans `fallback_order` INOFFENSIVE : la
    rotation place le backend demandé en tête, quelle que soit la liste.

    `fallback_order` ne décide donc pas de ce qu'on utilise, seulement de ce qui
    prend le relais — un choix de dépense, pas un câblage.
    """
    import inspect

    from src.llm import rotation

    source = inspect.getsource(rotation.clients)
    assert "[backend] +" in source, (
        "le backend actif n'est plus prioritaire sur les replis")


#: Le champ de `settings` que `models.py` lit réellement pour chaque backend.
#: Recopié ici À LA MAIN, et pas importé de `commands.py` : comparer la table de
#: l'implémentation à elle-même ne prouve rien. Le premier jet de ce test
#: vérifiait seulement que `_set_model` et `_current_model` visaient le MÊME
#: champ — or c'était déjà le cas avant le correctif : sur `nvidia` les deux
#: tombaient d'accord sur `ollama_model`. Le test passait sur le code bogué.
_CHAMP_ATTENDU = {
    "groq":         "groq_model",
    "ollama":       "ollama_model",
    "ollama_cloud": "ollama_cloud_model",
    "gemini":       "gemini_model",
    "mistral":      "mistral_model",
    "nvidia":       "nvidia_model",
}


def test_chaque_backend_declare_le_champ_qu_il_utilise():
    """Un backend ajouté sans entrée ici force une décision explicite."""
    manquants = [b for b in _BACKENDS if b not in _CHAMP_ATTENDU]
    assert not manquants, f"champ de modèle non décidé pour : {manquants}"


@pytest.mark.parametrize("backend", _BACKENDS)
def test_choisir_un_modele_ecrit_dans_le_champ_du_backend(backend):
    """Même famille que le bug des fabriques, dans l'UI cette fois.

    `_get_model_options` avait reçu sa branche `nvidia` ; `_current_model` et
    `_set_model` non. Les deux retombaient sur leur `else`, qui vise
    `settings.ollama_model`. Mesuré, backend actif `nvidia` :

        /model propose  meta/muse-glimmer-30b     (bonne liste)
        _current_model  → qwen2.5:7b              (modèle OLLAMA)
        _set_model      → settings.ollama_model   (models.py lit nvidia_model)

    Choisir un modèle NVIDIA ne changeait donc rien au modèle réellement appelé,
    et écrasait au passage le réglage Ollama local. Rien ne levait : les deux
    champs sont des chaînes, l'écriture réussissait.
    """
    import src.infra.settings as reglages
    from src.ui.commands import _current_model, _set_model

    s = reglages.settings
    precedent_backend = s.llm_backend
    champs = ("groq_model", "ollama_model", "ollama_cloud_model",
              "gemini_model", "mistral_model", "nvidia_model")
    avant = {c: getattr(s, c) for c in champs}
    try:
        s.llm_backend = backend
        _set_model(s, "SENTINELLE")

        assert _current_model(s) == "SENTINELLE", (
            f"{backend} : le modèle écrit n'est pas celui relu — "
            f"les deux fonctions ne visent pas le même champ")

        touches = [c for c in champs if getattr(s, c) != avant[c]]
        assert touches == [_CHAMP_ATTENDU[backend]], (
            f"{backend} : le choix atterrit dans {touches} au lieu de "
            f"['{_CHAMP_ATTENDU[backend]}'] — le champ que `models.py` lit")
    finally:
        for c, v in avant.items():
            setattr(s, c, v)
        s.llm_backend = precedent_backend


@pytest.mark.parametrize("backend", _BACKENDS)
def test_chaque_backend_propose_une_liste_de_modeles(backend):
    """Une liste vide rendrait le picker de `/model` inutilisable en silence."""
    from src.ui.commands import _get_model_options

    assert _get_model_options(backend), f"aucun modèle proposé pour {backend}"
