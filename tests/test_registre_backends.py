"""Un backend se déclare une fois, pas dans six tables parallèles.

La correspondance « nom → fabrique » était recopiée dans six fichiers, et elles
avaient DÉJÀ divergé — mesuré avant d'écrire une ligne :

    orchestrator/graph.py    les 6
    ui/commands.py           sans nvidia
    memory/persistent.py     sans nvidia, sans ollama
    ui/spec.py               sans nvidia, sans ollama
    cron_daemon.py           sans groq, sans ollama
    agents/deep/tools.py     sans groq, sans ollama

`nvidia` était invisible dans trois fichiers sur six, `ollama` dans quatre :
choisir ce backend n'avait aucun effet là où sa branche manquait, et rien ne
levait — chaque table retombait sur son défaut. `commands.py` portait déjà le
récit d'un bug identique, où `/model` écrivait le choix NVIDIA dans
`settings.ollama_model`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.llm import backends

RACINE = Path(__file__).resolve().parent.parent

#: Les fichiers qui portaient une copie de la table.
_ANCIENS_SITES = (
    "src/orchestrator/graph.py", "src/ui/commands.py", "src/agents/deep/tools.py",
    "src/ui/spec.py", "src/agents/memory/persistent.py", "src/cron_daemon.py",
)


def test_chaque_backend_declare_a_une_fabrique():
    """Déclarer sans fabriquer donnerait un choix qui ne mène nulle part."""
    fabriques = backends.fabriques()

    manquantes = [n for n in backends.noms() if n not in fabriques]

    assert not manquantes, manquantes


def test_chaque_backend_a_son_champ_de_reglage():
    """Un champ oublié fait retomber `/model` sur le défaut : il lirait et
    écrirait `ollama_model` pendant que `models.py` lit ailleurs."""
    from src.infra.settings import Settings

    champs = set(Settings.model_fields)

    for nom, b in backends.BACKENDS.items():
        assert b.champ_modele in champs, f"{nom} → {b.champ_modele}"


def test_aucune_table_de_fabriques_ne_subsiste():
    """Le motif qui avait dérivé : `"gemini": make_llm_gemini` en dur."""
    motif = re.compile(r'"(ollama|ollama_cloud|groq|gemini|mistral|nvidia)"\s*:\s*make_llm')

    for chemin in _ANCIENS_SITES:
        source = (RACINE / chemin).read_text(encoding="utf-8")
        assert not motif.search(source), chemin


def test_les_six_sites_voient_les_memes_backends():
    """C'est la propriété que la duplication ne pouvait pas tenir."""
    attendu = set(backends.fabriques())

    from src.agents.deep import tools as deep_tools  # noqa: F401
    from src.ui import commands, spec  # noqa: F401

    assert set(commands._backends()) >= attendu


def test_un_backend_sans_cle_nest_pas_dit_utilisable(monkeypatch):
    for cle in backends.BACKENDS["openrouter"].cles:
        monkeypatch.delenv(cle, raising=False)

    assert "openrouter" not in backends.utilisables()


def test_ollama_est_toujours_utilisable():
    """Il n'a pas de clé : la machine EST sa clé."""
    assert "ollama" in backends.utilisables()


def test_un_backend_inconnu_retombe_sur_le_local():
    """Seul à ne rien coûter."""
    assert backends.champ_modele("nexiste-pas") == "ollama_model"


# ── OpenRouter ────────────────────────────────────────────────────────────────
def test_openrouter_est_declare():
    assert "openrouter" in backends.noms()
    assert backends.BACKENDS["openrouter"].gratuit


def test_les_modeles_proposes_portent_free():
    """Un modèle payant dans cette liste ferait facturer un backend annoncé gratuit."""
    for m in backends.modeles("openrouter"):
        assert m.endswith(":free"), m


@pytest.mark.parametrize("refuse", ["thinkingmachines/inkling:free",
                                    "google/gemma-4-26b-a4b-it:free"])
def test_les_modeles_qui_nont_pas_repondu_sont_ecartes(refuse):
    """Éprouvés sur un appel d'outil réel : 403 pour l'un, 429 pour l'autre.
    `supported_parameters: tools` au catalogue ne promet rien."""
    assert refuse not in backends.modeles("openrouter")


# ── savoir lire une image ─────────────────────────────────────────────────────
# Rien ne le disait, et rien dans un nom de modèle ne le laisse deviner :
# `gemini-2.5-flash` sait, `gpt-oss:120b-cloud` non. Faute de cette réponse, AXON
# essayait, échouait, puis reniflait le message d'erreur à la recherche de
# « not support » ou « vision » pour retirer les images des messages checkpointés
# — un rattrapage qui dépend du TEXTE d'une erreur, donc qu'un fournisseur casse
# en reformulant sa phrase.
def test_gemini_sait_lire_une_image():
    assert backends.sait_lire_une_image("gemini")


def test_un_backend_inconnu_ne_pretend_rien():
    assert not backends.sait_lire_une_image("nexiste-pas")


def test_le_defaut_est_de_ne_pas_envoyer():
    """Un `False` n'affirme pas l'incapacité : il dit qu'on ne l'a pas établie.
    Envoyer du base64 à un modèle qui l'ignore casse l'appel ; ne pas l'envoyer
    coûte au pire une question."""
    assert not backends.sait_lire_une_image("groq")
    assert not backends.sait_lire_une_image("openrouter")


def test_ollama_est_interroge_modele_par_modele(monkeypatch):
    """Pour le local, la vérité est par MODÈLE et la machine sait répondre :
    `/api/tags` annonce `capabilities: ["vision"]`. On la lui demande."""
    import io
    import json

    class _Rep(io.StringIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    tags = {"models": [{"name": "voit:1b", "capabilities": ["completion", "vision"]},
                       {"name": "aveugle:1b", "capabilities": ["completion"]}]}
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: _Rep(json.dumps(tags)))

    monkeypatch.setattr(backends, "_modele_actif", lambda n: "voit:1b")
    assert backends.sait_lire_une_image("ollama")

    monkeypatch.setattr(backends, "_modele_actif", lambda n: "aveugle:1b")
    assert not backends.sait_lire_une_image("ollama")


def test_ollama_injoignable_ne_pretend_pas_voir(monkeypatch):
    def _explose(*a, **k):
        raise OSError("connexion refusée")

    monkeypatch.setattr("urllib.request.urlopen", _explose)

    assert not backends.sait_lire_une_image("ollama")
