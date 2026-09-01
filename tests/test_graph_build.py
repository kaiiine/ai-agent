"""L'agent pouvait interroger un graphe, jamais en construire un.

Sur un projet qui n'en a pas, les outils rendaient `no_graph` avec l'indice
« Lance /graph <projet> depuis Axon ». Or `/graph` est une commande de
l'INTERFACE : le modèle ne peut pas la taper, et n'a aucun moyen propre de te la
répercuter. Une impasse, dont il ressortait en lisant les fichiers un à un —
précisément ce que son prompt lui déconseille, chiffres à l'appui.

Mesuré sur 33 fichiers : construire coûte 4 secondes, sans clé ni modèle. Et la
question qui compte devient possible — « qui casse si je touche X » :

    graph_affected(barrer_le_code) → 5 appelants, dont `_handle_history()` dans
    commands.py, où le mot `barrer_le_code` NE FIGURE PAS : il passe par
    `final_panel`. Un appelant que grep ne peut pas trouver.

Sans le graphe, la même question demandait de lire 4 fichiers — 98 516
caractères, ≈ 24 600 tokens — et l'appelant transitif y restait invisible.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from src.agents.coding.graphe import graph_affected, graph_build

SOURCE = Path(__file__).resolve().parent.parent / "src" / "ui"


@pytest.fixture
def projet_neuf():
    """Une copie d'un vrai paquet, sans graphe."""
    cible = Path(tempfile.mkdtemp()) / "neuf"
    shutil.copytree(SOURCE, cible)
    shutil.rmtree(cible / "graphify-out", ignore_errors=True)
    return cible


def test_sans_graphe_lindice_est_desormais_appelable(projet_neuf):
    """Il renvoyait vers `/graph`, que le modèle ne peut pas taper."""
    resultat = graph_affected.invoke({"project_path": str(projet_neuf),
                                      "symbol": "barrer_le_code"})

    assert resultat["status"] == "no_graph"
    assert "graph_build" in resultat["hint"]


def test_construire_rend_le_graphe_interrogeable(projet_neuf):
    assert graph_build.invoke({"project_path": str(projet_neuf)})["status"] == "ok"

    resultat = graph_affected.invoke({"project_path": str(projet_neuf),
                                      "symbol": "barrer_le_code"})

    assert resultat["status"] == "ok"
    assert "final_panel" in resultat["result"]


def test_lappelant_transitif_apparait(projet_neuf):
    """`_handle_history()` appelle `final_panel`, qui appelle `barrer_le_code`.
    Le mot n'est pas dans `commands.py` : grep ne le trouve pas, le graphe si."""
    graph_build.invoke({"project_path": str(projet_neuf)})

    resultat = graph_affected.invoke({"project_path": str(projet_neuf),
                                      "symbol": "barrer_le_code"})

    assert "barrer_le_code" not in (projet_neuf / "commands.py").read_text(
        encoding="utf-8", errors="replace"), "prémisse du test"
    assert "commands.py" in resultat["result"]


def test_un_graphe_existant_nest_pas_reconstruit(projet_neuf):
    """Le rafraîchir est l'affaire de `update` — et surtout pas d'un silence qui
    laisserait croire qu'on vient de bâtir ce qui existait déjà."""
    graph_build.invoke({"project_path": str(projet_neuf)})

    second = graph_build.invoke({"project_path": str(projet_neuf)})

    assert second["status"] == "ok"
    assert "existe déjà" in second["message"]


def test_un_dossier_absent_est_une_erreur_franche():
    resultat = graph_build.invoke({"project_path": "/tmp/ce-dossier-nexiste-pas-du-tout"})

    assert resultat["status"] == "error"
    assert "introuvable" in resultat["error"]


def test_la_construction_nappelle_aucun_modele():
    """`--code-only` et `--no-label` : l'extraction sémantique de la doc et le
    nommage des communautés appellent un modèle, donc une clé et un coût. Un
    outil que l'agent déclenche seul ne doit engager ni l'un ni l'autre."""
    import inspect

    from src.agents.coding import graphe

    source = inspect.getsource(graphe.graph_build.func)

    assert "--code-only" in source
    assert "--no-label" in source


def test_loutil_est_dans_la_trousse_de_lagent():
    from src.agents.coding.specialist import _get_coding_tools

    assert "graph_build" in {o.name for o in _get_coding_tools()}
