"""Coquilles relevées à l'audit — chacune avec la raison qui la rendait invisible.

Ni bug spectaculaire ni refonte : des écarts qui ne se voient qu'au moment où ils
coûtent quelque chose. Un défaut latent n'est pas un défaut absent.
"""

from __future__ import annotations

from datetime import date

import pytest


# ── Le défaut Python et le YAML doivent dire la même chose ──────────────────

def test_le_modele_de_code_par_defaut_suit_le_yaml():
    """Le défaut Python ne sert que si le YAML manque : l'écart ne se voyait
    jamais — jusqu'au jour où le YAML manque."""
    import pathlib
    import re

    from src.infra.settings import Settings

    yaml = pathlib.Path("configs/base.yaml").read_text(encoding="utf-8")
    attendu = re.search(r'^coding_model:\s*"([^"]+)"', yaml, re.MULTILINE).group(1)

    assert Settings().coding_model == attendu


def test_le_defaut_de_lecture_yaml_suit_aussi():
    """Deux endroits portent ce défaut : la dataclass et le `yml.get`."""
    import inspect

    import src.infra.settings as settings

    source = inspect.getsource(settings)

    assert 'yml.get("coding_model", "minimax-m3:cloud")' in source


# ── Un docstring qui nomme un modèle ment au premier changement de backend ──

def test_le_specialist_ne_nomme_aucun_modele_en_dur():
    from src.agents.coding import specialist

    assert "qwen3-coder" not in (specialist.__doc__ or "")
    assert "settings.coding_model" in (specialist.__doc__ or "")


# ── Le décomposeur de /build mourait en silence sur un seul 429 ─────────────

def test_le_decomposeur_passe_par_la_rotation():
    """Sans elle, un 429 sur CE seul appel faisait retomber tout le /build sur
    les phases génériques — quelles que soient les autres clés configurées."""
    import inspect

    from src.agents.coding import task_decomposer

    source = inspect.getsource(task_decomposer.decompose)

    assert "rotation.clients" in source
    assert "make_coding_llm_with_key" in source


def test_le_decomposeur_essaie_les_cles_suivantes_apres_un_quota(monkeypatch):
    from src.agents.coding import task_decomposer
    from src.llm import rotation

    essais = []

    class _LLM:
        def __init__(self, fournisseur, cle):
            self.cle = cle

        def invoke(self, _messages):
            essais.append(self.cle)
            if len(essais) < 3:
                raise RuntimeError("429 rate limit")
            return type("R", (), {"content": '{"phases":[{"title":"OK","scope":"x"}]}'})()

    monkeypatch.setattr(rotation, "clients", lambda b, f, **k: (
        (fournisseur, cle, _LLM(fournisseur, cle))
        for fournisseur, cle in (("ollama_cloud", "o1"), ("ollama_cloud", "o2"),
                                 ("gemini", "g1"))))
    monkeypatch.setattr(rotation, "marquer_echec", lambda *a: None)

    phases = task_decomposer.decompose("## Spec\ncontenu", "ollama_cloud")

    assert essais == ["o1", "o2", "g1"]
    assert [p.title for p in phases] == ["OK"], "le repli générique a mangé le résultat"


def test_une_erreur_qui_n_est_pas_un_quota_ne_brule_pas_les_cles(monkeypatch):
    """Réessayer une erreur sans rapport gaspillerait toutes les clés."""
    from src.agents.coding import task_decomposer
    from src.llm import rotation

    essais = []

    class _LLM:
        def invoke(self, _messages):
            essais.append(1)
            raise RuntimeError("prompt trop long")

    monkeypatch.setattr(rotation, "clients", lambda b, f, **k: (
        (p, c, _LLM()) for p, c in (("ollama_cloud", "o1"), ("ollama_cloud", "o2"))))

    phases = task_decomposer.decompose("## Spec", "ollama_cloud")

    assert len(essais) == 1
    assert phases == task_decomposer._FALLBACK_PHASES


def test_un_json_illisible_laisse_sa_chance_au_modele_suivant(monkeypatch):
    from src.agents.coding import task_decomposer
    from src.llm import rotation

    reponses = iter(["pas du json", '{"phases":[{"title":"Bon","scope":"y"}]}'])

    class _LLM:
        def invoke(self, _messages):
            return type("R", (), {"content": next(reponses)})()

    monkeypatch.setattr(rotation, "clients", lambda b, f, **k: (
        (p, c, _LLM()) for p, c in (("ollama_cloud", "o1"), ("ollama_cloud", "o2"))))

    assert [p.title for p in task_decomposer.decompose("## S", "ollama_cloud")] == ["Bon"]


# ── Fraîcheur du jeu de données tennis ─────────────────────────────────────

@pytest.fixture(scope="module")
def dataset_atp():
    from src.agents.quant.betting_engine.sports.tennis.tennis_data_loader import (
        load_tennis_data,
    )

    return load_tennis_data("atp")


def test_la_fraicheur_est_rendue_en_jours_pas_en_dates_brutes(dataset_atp):
    """« période : 2000-01-03 → 2026-07-26 » ne dit pas « 17 jours de retard »."""
    from src.agents.quant.betting_engine.sports.tennis.inventory import freshness

    f = freshness(dataset_atp, today=date(2026, 8, 12))

    assert f["age_jours"] == 17
    assert f["derniere_date"] == "2026-07-26"


def test_un_retard_au_dela_du_seuil_est_declare_perime(dataset_atp):
    from src.agents.quant.betting_engine.sports.tennis.inventory import freshness

    assert freshness(dataset_atp, today=date(2026, 10, 1))["perime"] is True
    assert freshness(dataset_atp, today=date(2026, 7, 28))["perime"] is False


def test_le_rendu_affiche_le_verdict_de_fraicheur(dataset_atp):
    from src.agents.quant.betting_engine.sports.tennis.inventory import render

    lignes = render(dataset_atp, today=date(2026, 10, 1))

    assert any("PÉRIMÉ" in l for l in lignes)
    assert any("jour(s) de retard" in l for l in lignes)


def test_la_fraicheur_ne_compte_pas_les_joueurs_retraites(dataset_atp):
    """Sur 26 ans d'archive, « 1760/1780 joueurs sans match récent » est du bruit :
    la péremption qui compte est celle des deux joueurs d'une affiche, et elle est
    déjà signalée à la prédiction."""
    from src.agents.quant.betting_engine.sports.tennis.inventory import freshness

    assert "joueurs_perimes" not in freshness(dataset_atp, today=date(2026, 8, 12))


def test_le_seuil_de_fraicheur_est_celui_du_modele(dataset_atp):
    """Deux seuils divergeraient : l'inventaire dirait « à jour » quand le modèle
    crie « périmé »."""
    from src.agents.quant.betting_engine.sports.tennis.inventory import freshness
    from src.agents.quant.betting_engine.sports.tennis.live_model import PEREMPTION_JOURS

    assert freshness(dataset_atp)["seuil_jours"] == PEREMPTION_JOURS


# ── Banc de mesure des prompts ─────────────────────────────────────────────

def test_le_readme_des_variantes_n_est_pas_mesure_comme_un_prompt():
    """`variantes/*.md` devient un bras : le README du dossier en devenait un."""
    import sys

    sys.path.insert(0, ".")
    from benchmarks.prompt_bench import _bras

    assert "README" not in _bras()
    assert {"aucun", "actuel"} <= set(_bras())


def test_le_bras_actuel_lit_le_prompt_de_production():
    """Une copie figée se comparerait à elle-même après la première évolution."""
    import sys

    sys.path.insert(0, ".")
    from benchmarks.prompt_bench import _bras
    from src.agents.coding.prompts import BASE_PROMPT

    assert _bras()["actuel"] == BASE_PROMPT
