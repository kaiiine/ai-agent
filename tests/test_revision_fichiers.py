"""La revue des fichiers proposés, portée par le graphe.

C'était le producteur de HITL le plus ancien et le plus utilisé, et il vivait
dans la boucle de flux du TUI : le tour se terminait, puis le terminal vidait
`pending_changes`. Appelé par l'API, rien ne la vidait — les fichiers proposés
restaient proposés, sans que personne le dise.

Un changement de comportement assumé accompagne le déplacement : la revue arrive
maintenant juste après l'outil qui a proposé, et non à la fin du tour.
"""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents.coding.pending import FileChange, pending_changes
from src.orchestrator.hitl import DIFF, demande_en_attente, reponse
from src.orchestrator.revision import (
    APPLIQUER,
    PRECISER,
    REFUSER,
    appliquer,
    reviser,
    revision_attendue,
)


class _Etat(TypedDict):
    messages: list


@pytest.fixture(autouse=True)
def file_propre():
    pending_changes.clear()
    yield
    pending_changes.clear()


@pytest.fixture
def cible(tmp_path):
    chemin = tmp_path / "sous" / "f.py"
    pending_changes.add(FileChange(path=str(chemin), original="",
                                   proposed="print(1)\n", description="crée f.py"))
    return chemin


def _graphe():
    g = StateGraph(_Etat)
    g.add_node("reviser", reviser)
    g.add_edge(START, "reviser")
    g.add_edge("reviser", END)
    return g.compile(checkpointer=MemorySaver())


# ── Quand demander ───────────────────────────────────────────────────────────
def test_rien_a_relire_ne_declenche_rien():
    assert not revision_attendue()


def test_le_mode_auto_ne_demande_pas(cible, monkeypatch):
    """Il écrit sans demander — c'est sa définition. Entrer dans le nœud
    fabriquerait une interruption que personne n'attend."""
    import src.ui.edit_mode as mode

    monkeypatch.setattr(mode, "get_mode", lambda: "auto")
    assert not revision_attendue()

    monkeypatch.setattr(mode, "get_mode", lambda: "ask")
    assert revision_attendue()


# ── Le graphe s'arrête et montre ─────────────────────────────────────────────
def test_le_graphe_s_arrete_et_porte_les_changements(cible, monkeypatch):
    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    app = _graphe()
    cfg = {"configurable": {"thread_id": "revue"}}
    demande = demande_en_attente(app.invoke({"messages": []}, cfg))

    assert demande is not None
    assert demande.genre == DIFF
    assert str(cible) in demande.cle
    # Les deux formes coexistent : un texte pour les clients qui n'ont que ça,
    # les changements complets pour ceux qui savent afficher un diff.
    assert "f.py" in demande.apercu
    assert demande.extra["changements"][0]["proposed"] == "print(1)\n"
    assert demande.questions[0].choix == (APPLIQUER, REFUSER, PRECISER)


# ── Les trois issues ─────────────────────────────────────────────────────────
def test_appliquer_ecrit_le_fichier(cible, monkeypatch):
    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    app = _graphe()
    cfg = {"configurable": {"thread_id": "appliquer"}}
    app.invoke({"messages": []}, cfg)
    finale = app.invoke(reponse([APPLIQUER, ""]), cfg)

    assert cible.read_text() == "print(1)\n"
    assert not pending_changes.items, "la file doit être vidée"
    assert "f.py" in finale["messages"][-1].content


def test_refuser_n_ecrit_rien(cible, monkeypatch):
    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    app = _graphe()
    cfg = {"configurable": {"thread_id": "refuser"}}
    app.invoke({"messages": []}, cfg)
    finale = app.invoke(reponse([REFUSER, ""]), cfg)

    assert not cible.exists()
    assert not pending_changes.items
    assert "refusé" in finale["messages"][-1].content.lower()


def test_preciser_n_ecrit_rien_et_transmet_la_demande(cible, monkeypatch):
    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    app = _graphe()
    cfg = {"configurable": {"thread_id": "preciser"}}
    app.invoke({"messages": []}, cfg)
    finale = app.invoke(reponse([PRECISER, "utilise print(2) plutôt"]), cfg)

    assert not cible.exists()
    assert "print(2)" in finale["messages"][-1].content, (
        "sans la précision, le modèle referait exactement la même proposition")


@pytest.mark.parametrize("decision", ["", "n'importe quoi", "APPLIQUER "])
def test_une_reponse_qui_n_est_pas_APPLIQUER_n_ecrit_rien(cible, decision, monkeypatch):
    """Un client en panne, une fenêtre fermée ou une réponse mal orthographiée
    ne doivent pas écrire sur le disque. Seul le libellé exact applique."""
    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    app = _graphe()
    cfg = {"configurable": {"thread_id": f"strict-{decision or 'vide'}"}}
    app.invoke({"messages": []}, cfg)
    app.invoke(reponse([decision, ""]), cfg)

    assert not cible.exists(), f"« {decision} » a écrit sur le disque"


def test_le_fichier_n_est_ecrit_QU_UNE_fois_malgre_le_rejeu(tmp_path, monkeypatch):
    """LangGraph rejoue le nœud à la reprise. Une écriture placée avant
    l'interruption aurait lieu deux fois — ici elle est après, et le compteur
    le prouve."""
    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    ecritures: list[str] = []
    chemin = tmp_path / "compte.txt"
    pending_changes.add(FileChange(path=str(chemin), original="",
                                   proposed="x", description="d"))

    import src.orchestrator.revision as revision
    vrai = revision.appliquer
    monkeypatch.setattr(revision, "appliquer",
                        lambda c: (ecritures.append("appel"), vrai(c))[1])

    app = _graphe()
    cfg = {"configurable": {"thread_id": "rejeu-diff"}}
    app.invoke({"messages": []}, cfg)
    app.invoke(reponse([APPLIQUER, ""]), cfg)

    assert ecritures == ["appel"], f"écriture dupliquée : {ecritures}"


# ── L'écriture elle-même ─────────────────────────────────────────────────────
def test_un_echec_sur_un_fichier_ne_fait_pas_perdre_les_autres(tmp_path):
    """Une permission refusée sur l'un ne doit pas faire perdre les suivants,
    déjà relus et approuvés."""
    bon = tmp_path / "bon.py"
    changements = [
        FileChange(path="/racine_interdite/impossible.py", original="",
                   proposed="x", description="d"),
        FileChange(path=str(bon), original="", proposed="ok", description="d"),
    ]
    appliques, erreurs = appliquer(changements)

    assert appliques == [str(bon)]
    assert len(erreurs) == 1
    assert bon.read_text() == "ok"


def test_les_dossiers_manquants_sont_crees(tmp_path):
    cible = tmp_path / "a" / "b" / "c.py"
    appliques, erreurs = appliquer([FileChange(path=str(cible), original="",
                                               proposed="x", description="d")])
    assert not erreurs and cible.read_text() == "x"


# ── Les cellules de notebook, dans le MÊME nœud ──────────────────────────────
@pytest.fixture
def cellule(tmp_path):
    """Un notebook réel et une cellule en attente."""
    import json

    from src.agents.notebook.tools import CellChange, pending_cell_changes

    carnet = tmp_path / "n.ipynb"
    carnet.write_text(json.dumps({
        "cells": [{"cell_type": "code", "source": ["print(0)\n"],
                   "metadata": {}, "outputs": [], "execution_count": None}],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))
    pending_cell_changes.clear()
    pending_cell_changes.add(CellChange(
        path=str(carnet), cell_index=0, insert_after=-1, cell_type="code",
        original_source="print(0)\n", proposed_source="print(42)\n",
        description="corrige la valeur"))
    yield carnet
    pending_cell_changes.clear()


def test_une_cellule_declenche_la_meme_revue(cellule, monkeypatch):
    """Les cellules avaient leur propre revue, leur propre appel dans la boucle
    de flux et leur propre rendu — pour la même intention exactement : montrer un
    changement avant de l'écrire."""
    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    assert revision_attendue()

    app = _graphe()
    cfg = {"configurable": {"thread_id": "cellule"}}
    demande = demande_en_attente(app.invoke({"messages": []}, cfg))

    assert demande.genre == DIFF
    assert demande.extra["cellules"][0]["proposed_source"] == "print(42)\n"
    assert "cellule 0" in demande.apercu


def test_appliquer_ecrit_la_cellule(cellule, monkeypatch):
    import json

    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    app = _graphe()
    cfg = {"configurable": {"thread_id": "cellule-ok"}}
    app.invoke({"messages": []}, cfg)
    app.invoke(reponse([APPLIQUER, ""]), cfg)

    contenu = json.loads(cellule.read_text())
    assert "print(42)" in "".join(contenu["cells"][0]["source"])


def test_refuser_laisse_la_cellule_intacte(cellule, monkeypatch):
    import json

    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    app = _graphe()
    cfg = {"configurable": {"thread_id": "cellule-non"}}
    app.invoke({"messages": []}, cfg)
    app.invoke(reponse([REFUSER, ""]), cfg)

    contenu = json.loads(cellule.read_text())
    assert "print(0)" in "".join(contenu["cells"][0]["source"])


def test_lire_les_cellules_ne_vide_PAS_la_file(cellule):
    """Le nœud MONTRE puis décide, et le graphe rejoue le nœud entre les deux.
    La seule lecture disponible était `pop_latest`, qui consommait : au rejeu,
    il n'aurait plus rien trouvé et la revue se serait volatilisée."""
    from src.agents.notebook.tools import pending_cell_changes

    assert len(pending_cell_changes.items) == 1
    assert len(pending_cell_changes.items) == 1, "la lecture a consommé la file"


def test_fichiers_et_cellules_se_relisent_ENSEMBLE(cible, cellule, monkeypatch):
    """Un seul questionnaire pour tout ce qui attend : deux demandes successives
    feraient répondre à la seconde sur un contexte qu'on ne voit plus."""
    import src.ui.edit_mode as mode
    monkeypatch.setattr(mode, "get_mode", lambda: "ask")

    app = _graphe()
    cfg = {"configurable": {"thread_id": "les-deux"}}
    demande = demande_en_attente(app.invoke({"messages": []}, cfg))

    assert len(demande.extra["changements"]) == 1
    assert len(demande.extra["cellules"]) == 1
    assert "2 modifications" in demande.questions[0].texte
