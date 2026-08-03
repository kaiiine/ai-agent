"""Rotation de clés / bascule de provider — la bascule automatique doit être TEMPORAIRE.

Bug corrigé : un rate-limit faisait basculer `settings.llm_backend` vers un provider de
secours de façon PERMANENTE (écriture globale jamais annulée). Toute la session restait
sur le secours — même après expiration du cooldown et alors que le provider préféré avait
de nouveau des clés saines. Symptôme utilisateur : « mes clés ollama sont dispo mais tout
part sur gemini qui est surchargé ».
"""

from __future__ import annotations

import time
import types

import pytest

from src.llm import key_pool as kp


@pytest.fixture(autouse=True)
def _clean_state():
    kp.clear_auto_fallback()
    yield
    kp.clear_auto_fallback()


def _settings(backend: str):
    return types.SimpleNamespace(llm_backend=backend)


class _Pool(kp.KeyPool):
    """Pool isolé : clés en mémoire, aucune écriture disque."""

    def __init__(self, keys: dict[str, list[str]]):
        self._keys = keys
        self._exhausted = {}

    def keys_for(self, provider: str) -> list[str]:
        return list(self._keys.get(provider, []))

    def _save(self) -> None:      # jamais de persistance en test
        pass


# ── Bascule automatique = réversible ─────────────────────────────────────────────
def test_auto_fallback_returns_to_preferred_when_healthy(monkeypatch):
    monkeypatch.setattr(kp, "_pool", _Pool({"ollama_cloud": ["k1"], "gemini": ["g1"]}))
    s = _settings("gemini")
    kp.note_auto_fallback("ollama_cloud", "gemini")      # bascule subie, pas choisie
    assert kp.restore_preferred_backend(s) == "ollama_cloud"
    assert s.llm_backend == "ollama_cloud"


def test_no_return_while_preferred_still_exhausted(monkeypatch):
    pool = _Pool({"ollama_cloud": ["k1"], "gemini": ["g1"]})
    pool.mark_rate_limited("ollama_cloud", "k1")          # toujours en cooldown
    monkeypatch.setattr(kp, "_pool", pool)
    s = _settings("gemini")
    kp.note_auto_fallback("ollama_cloud", "gemini")
    assert kp.restore_preferred_backend(s) is None
    assert s.llm_backend == "gemini"                      # on reste sur le secours


def test_explicit_user_backend_choice_is_never_overridden(monkeypatch):
    monkeypatch.setattr(kp, "_pool", _Pool({"ollama_cloud": ["k1"], "mistral": ["m1"]}))
    s = _settings("gemini")
    kp.note_auto_fallback("ollama_cloud", "gemini")
    s.llm_backend = "mistral"                             # l'utilisateur fait /backend mistral
    assert kp.restore_preferred_backend(s) is None
    assert s.llm_backend == "mistral"                     # choix respecté


def test_restore_is_noop_without_auto_fallback(monkeypatch):
    monkeypatch.setattr(kp, "_pool", _Pool({"ollama_cloud": ["k1"]}))
    s = _settings("gemini")                               # backend choisi volontairement
    assert kp.restore_preferred_backend(s) is None
    assert s.llm_backend == "gemini"


# ── Rotation : peut revenir vers un provider PRIORITAIRE sain ────────────────────
def test_rotation_can_go_back_to_higher_priority_provider(monkeypatch):
    pool = _Pool({"ollama_cloud": ["k1"], "gemini": ["g1"], "mistral": ["m1"]})
    order = ["ollama_cloud", "gemini", "mistral"]
    # On est sur gemini, sa seule clé casse -> ollama_cloud (prioritaire) est sain.
    nxt = pool.next_provider_and_key("gemini", "g1", order)
    assert nxt is not None and nxt[0] == "ollama_cloud"    # avant : mistral uniquement


def test_rotation_prefers_another_key_of_same_provider_first(monkeypatch):
    pool = _Pool({"ollama_cloud": ["k1", "k2"], "gemini": ["g1"]})
    nxt = pool.next_provider_and_key("ollama_cloud", "k1", ["ollama_cloud", "gemini"])
    assert nxt == ("ollama_cloud", "k2")                  # pas de bascule prématurée


def test_exhausted_key_is_really_cooled_down(monkeypatch):
    pool = _Pool({"ollama_cloud": ["k1"], "gemini": ["g1"]})
    pool.next_provider_and_key("ollama_cloud", "k1", ["ollama_cloud", "gemini"])
    assert pool.next_healthy("ollama_cloud") is None      # k1 en cooldown
    assert time.time() < pool._exhausted["ollama_cloud"]["k1"]


# ── Le cron doit être retrouvable pour une demande récurrente (bug « n'importe quoi ») ──
def test_schedule_task_anchors_cover_daily_recurrence():
    from src.orchestrator.tool_retriever import _TOOL_ANCHORS, TOOL_GROUPS

    anchors = " | ".join(_TOOL_ANCHORS["schedule_task"]).lower()
    for phrasing in ("tous les jours", "chaque jour", "quotidien", "every day", "planifie"):
        assert phrasing in anchors, f"ancre cron manquante : {phrasing}"
    # le groupe complet suit dès que schedule_task est retrouvé
    assert {"schedule_task", "list_cron_tasks", "stop_cron_task"} == set(TOOL_GROUPS["cron"])


def test_slack_anchors_cover_channel_phrasings():
    """Sans ancre, « envoie un retour sur le canal test-cron » ne matchait aucun outil
    Slack (leur description contient « Slack », pas « canal ») : l'agent n'avait pas de
    quoi poster et demandait « est-ce un canal Slack ? » au lieu d'agir."""
    from src.orchestrator.tool_retriever import _TOOL_ANCHORS

    anchors = " | ".join(_TOOL_ANCHORS["slack_send_message"]).lower()
    for phrasing in ("canal", "channel", "poste", "envoie"):
        assert phrasing in anchors, f"ancre slack manquante : {phrasing}"


def test_tool_names_in_groups_all_exist():
    """Un nom d'outil mal orthographié dans TOOL_GROUPS rend l'outil INTROUVABLE en
    silence (la sélection filtre par `t.name`)."""
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import TOOL_GROUPS, _TOOL_ANCHORS

    real = {t.name for t in build_all_tools()}
    declared = {n for names in TOOL_GROUPS.values() for n in names}
    missing = declared - real
    assert not missing, f"outils déclarés mais inexistants : {sorted(missing)}"
    anchored_missing = set(_TOOL_ANCHORS) - real
    assert not anchored_missing, f"ancres sur des outils inexistants : {sorted(anchored_missing)}"
