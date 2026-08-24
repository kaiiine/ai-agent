"""Aucun nom indéfini dans `src/` — la classe de bug qui casse à l'exécution.

Ce fichier existe parce que `/build axon-landing` s'est arrêté net sur :

    UnboundLocalError: cannot access local variable 'task'

Le préfixe de pré-scaffold concaténait `task` avant que `task` n'existe. La
tâche avait été déplacée dans la boucle de tentatives, le préfixe était resté
au-dessus. Rien ne l'avait vu parce que rien n'exécute ce chemin : il demande un
projet déjà scaffoldé, une phase de scaffold, et un vrai modèle derrière.

Or `pyflakes` le voyait, en une seconde, sans rien exécuter — et il n'était pas
lancé. Le même passage a révélé deux autres crashs de la même famille :

    src/infra/mcp_gmail.py       une frappe parasite collée avant la 1re ligne
    …/acquisition/api_sports.py  `_total` appelé sans être importé

Le test ne vise QUE les fautes qui cassent à l'exécution. Les imports inutilisés
sont du désordre, pas des pannes : les inclure rendrait ce test rouge en
permanence, et un test toujours rouge ne protège plus de rien — c'est d'ailleurs
un `nonlocal` superflu qui masquait le `task` non défini dans la même sortie.
"""
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent

#: Les catégories qui font tomber le programme. `undefined name` couvre aussi
#: bien la variable lue trop tôt que la frappe parasite ; `redefinition` attrape
#: la fonction écrasée par une homonyme, dont la première version devient morte
#: sans que personne ne s'en aperçoive.
FAUTES_FATALES = ("undefined name", "referenced before assignment")


def _pyflakes(cible: str) -> list[str]:
    sortie = subprocess.run(
        [sys.executable, "-m", "pyflakes", cible],
        cwd=RACINE, capture_output=True, text=True, timeout=300,
    ).stdout
    return [l for l in sortie.splitlines()
            if any(f in l for f in FAUTES_FATALES)]


def test_aucun_nom_indefini_dans_src():
    """Trois crashs réels dormaient dans l'arbre, tous invisibles aux tests et
    tous visibles ici."""
    fautes = _pyflakes("src")

    assert not fautes, "noms indéfinis — plantage garanti à l'exécution :\n" + "\n".join(fautes)


def test_le_garde_detecte_vraiment_un_nom_indefini(tmp_path):
    """Un garde qu'on ne vérifie pas peut être devenu aveugle sans qu'on le
    sache — il passerait au vert en ayant cessé de regarder."""
    piege = tmp_path / "piege.py"
    piege.write_text("def f():\n    return valeur_jamais_definie\n")

    assert _pyflakes(str(piege)), "le garde ne voit plus les noms indéfinis"


def test_le_prefixe_de_prescaffold_suit_la_tache():
    """Le bug d'origine, dit en termes de code : l'avertissement « ne relance pas
    pnpm create » doit être posé APRÈS la construction de la tâche, et DANS la
    boucle de tentatives.

    Placé avant, il plante — c'est l'`UnboundLocalError` vu sur `/build`. Placé
    après mais hors de la boucle, il disparaît de la seconde tentative : celle
    qui relancerait le scaffold sur un projet déjà scaffoldé, ce que
    l'avertissement existe précisément pour empêcher.

    Le test vise l'ORDRE, pas la forme : le préfixe a été extrait en
    `_prefixe_prescaffold()` pour être testable sans dérouler un build entier, et
    cette factorisation ne doit pas faire tomber le garde.
    """
    import inspect

    # La boucle de phases vit dans `_run_build`, pas dans `run_build` : cette
    # dernière n'est plus que l'enveloppe qui l'entoure.
    from src.agents.coding.build_runner import _run_build

    source = inspect.getsource(_run_build)
    construction = source.index("task = _build_phase_task(")
    prefixe = source.index("_prefixe_prescaffold(")
    tentatives = source.index("for attempt in range(")

    assert construction < prefixe, "le préfixe s'ajoute à une tâche qui n'existe pas encore"
    assert tentatives < prefixe, "le préfixe manquerait à la seconde tentative"


def test_le_prefixe_de_prescaffold_est_isolable():
    """Il vivait dans `run_build`, où il était devenu du code mort en plantant.
    Isolé, il se teste sans dérouler un build."""
    from src.agents.coding.build_runner import _prefixe_prescaffold

    texte = _prefixe_prescaffold("Next.js")

    assert "Next.js" in texte
    assert "NE PAS relancer" in texte
