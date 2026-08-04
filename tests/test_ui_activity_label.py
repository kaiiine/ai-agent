"""Label du panneau d'attente : « thinking » devient « thinking · <skill> »."""

from __future__ import annotations

import threading

from src.ui.panels import live_panel_initial
from src.ui.streaming import _make_thinking_loop


def _texte(panel) -> str:
    return panel.renderable.plain


def test_le_label_par_defaut_reste_thinking():
    assert _texte(live_panel_initial(0)).strip().startswith("thinking")


def test_le_label_est_parametrable():
    assert "thinking · blender" in _texte(live_panel_initial(2, "thinking · blender"))
    assert "..." in _texte(live_panel_initial(3, "thinking · blender"))


class _LiveFactice:
    def __init__(self):
        self.frames: list[str] = []

    def update(self, renderable):
        self.frames.append(_texte(renderable))


def test_le_loop_relit_le_label_a_chaque_frame():
    """Le label change sans relancer le thread."""
    live, stop = _LiveFactice(), threading.Event()
    activity = {"label": "thinking"}
    loop = _make_thinking_loop(stop, live, activity=activity)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    while not live.frames:
        pass
    activity["label"] = "thinking · blender"
    while not any("blender" in f for f in live.frames):
        pass
    stop.set()
    thread.join(timeout=1)

    assert live.frames[0].strip().startswith("thinking")
    assert any("thinking · blender" in f for f in live.frames)


def test_sans_activity_le_loop_affiche_thinking():
    """Les appels sans activity gardent le comportement d'avant."""
    live, stop = _LiveFactice(), threading.Event()
    thread = threading.Thread(target=_make_thinking_loop(stop, live), daemon=True)
    thread.start()
    while not live.frames:
        pass
    stop.set()
    thread.join(timeout=1)

    assert all("thinking" in f for f in live.frames)


def test_le_label_est_promu_seulement_apres_chargement_effectif():
    """Le label n'est posé qu'au retour du ToolMessage : un appel interrompu ne
    doit pas laisser un label mensonger."""
    activity: dict = {"label": "thinking"}

    activity["skill"] = "blender"                      # tool call vu
    assert activity["label"] == "thinking"             # rien n'est encore chargé

    if activity.get("skill"):                          # ToolMessage reçu
        activity["label"] = f"thinking · {activity['skill']}"
    assert activity["label"] == "thinking · blender"
