"""AXON ne doit pas dépendre d'un dossier voisin.

`graphe.py` et la commande `/graph` injectaient
`~/Documents/projets-perso/graphify` en `PYTHONPATH` avant chaque appel. Ça
marchait — le dépôt était là — mais :

  · déplacer ou renommer le dossier faisait tomber `/graph` et les quatre outils ;
  · un clone neuf d'AXON n'avait rien, et rien ne le disait ;
  · `graphifyy` n'était pas dans `requirements.txt`, donc la dépendance était
    invisible ;
  · l'injection MASQUAIT qu'une installation ordinaire suffisait : le paquet
    était déjà dans le venv, en mode editable pointant sur le dépôt.

`graphifyy` est publié sur PyPI. C'est une dépendance comme une autre.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
_DEPOT_VOISIN = "projets-perso/graphify"


def test_aucun_chemin_vers_le_depot_voisin():
    for module in ("src/agents/coding/graphe.py", "src/ui/commands.py"):
        source = (RACINE / module).read_text(encoding="utf-8")
        lignes = [l for l in source.splitlines()
                  if _DEPOT_VOISIN in l and not l.strip().startswith("#")]
        assert not lignes, f"{module} pointe encore sur le dépôt : {lignes}"


def test_aucune_injection_de_pythonpath():
    """L'injection masquait qu'une installation ordinaire suffisait."""
    source = (RACINE / "src/agents/coding/graphe.py").read_text(encoding="utf-8")
    code = [l for l in source.splitlines()
            if "PYTHONPATH" in l and not l.strip().startswith("#")]

    assert not code, code


def test_la_dependance_est_declaree():
    """Sans ça, un clone neuf perd `/graph` et les outils graph_* en silence."""
    requis = (RACINE / "requirements.txt").read_text(encoding="utf-8")

    assert "graphifyy" in requis


def test_graphify_sappelle_comme_un_module_installe():
    pytest.importorskip("graphify")
    import graphify

    assert _DEPOT_VOISIN not in graphify.__file__, (
        "graphify est résolu depuis le dépôt voisin — installation editable ?")


def test_la_commande_repond_sans_le_depot():
    pytest.importorskip("graphify")
    p = subprocess.run([sys.executable, "-m", "graphify", "--help"],
                       capture_output=True, text=True, timeout=60)

    assert p.returncode == 0
    assert "Usage: graphify" in p.stdout


# ── la dérive silencieuse ─────────────────────────────────────────────────────
# Le graphe de ce dépôt datait de cinq jours et annonçait `revision.py L78` pour
# une fonction passée ligne 162. L'agent citait des positions fausses, et rien ne
# le signalait — ni à lui, ni à personne. Un graphe périmé est pire qu'absent :
# absent, on le sait.
@pytest.fixture
def depot(tmp_path):
    """Un dépôt git minuscule, son graphe, et de quoi le faire vieillir."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True)
    sortie = tmp_path / "graphify-out"
    sortie.mkdir()
    graphe = sortie / "graph.json"
    graphe.write_text("{}", encoding="utf-8")
    return tmp_path, graphe


def test_un_graphe_a_jour_ne_dit_rien(depot):
    from src.agents.coding.graphe import _derive

    projet, graphe = depot

    assert _derive(projet, graphe) == ""


def test_une_source_plus_recente_est_signalee(depot):
    from src.agents.coding.graphe import _derive

    projet, graphe = depot
    time.sleep(0.01)
    (projet / "a.py").write_text("x = 2\n", encoding="utf-8")

    message = _derive(projet, graphe)

    assert "PÉRIMÉ" in message
    assert "--update" in message


def test_le_signal_accompagne_le_resultat_sans_le_bloquer(depot, monkeypatch):
    """Consultatif : on ne refuse jamais de répondre, on dit ce qu'on sait."""
    from src.agents.coding import graphe as g

    projet, _ = depot
    time.sleep(0.01)
    (projet / "a.py").write_text("x = 3\n", encoding="utf-8")

    # Seul l'appel à graphify est simulé : celui de `_derive` est un vrai `git`,
    # et l'intercepter aussi rendait la dérive invisible — le test passait à côté
    # de ce qu'il vérifie.
    vrai = subprocess.run

    def faux(commande, *a, **k):
        if "graphify" in " ".join(str(m) for m in commande):
            return type("P", (), {"returncode": 0, "stdout": "Node: a", "stderr": ""})()
        return vrai(commande, *a, **k)

    monkeypatch.setattr(g.subprocess, "run", faux)

    resultat = g._lancer(projet, "explain", "a")

    assert resultat["status"] == "ok"
    assert resultat["result"] == "Node: a"
    assert "PÉRIMÉ" in resultat["stale"]


def test_hors_dun_depot_git_on_ne_dit_rien(tmp_path):
    """Pas de git, pas de verdict — mieux vaut se taire que se tromper."""
    from src.agents.coding.graphe import _derive

    graphe = tmp_path / "graph.json"
    graphe.write_text("{}", encoding="utf-8")

    assert _derive(tmp_path, graphe) == ""
