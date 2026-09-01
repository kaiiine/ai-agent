"""Écrire un fichier n'achève pas forcément une étape.

Vécu : « Créer le fichier tri.py » est restée EN COURS alors que le fichier était
écrit, relu et exécuté avec succès — le modèle n'appelle presque jamais
`dev_plan_step_done`. Une étape ouverte fait croire à du travail restant.

La cocher automatiquement était tentant et faux : une étape peut demander
plusieurs fichiers (« mettre à jour les imports dans main.py ET utils.py »),
plusieurs passes sur le même, ou une écriture ET un test. Seul le modèle sait où
il en est. On lui rappelle donc l'étape ; on ne décide pas à sa place.
"""
from __future__ import annotations

import pytest

from src.agents.coding.pending import dev_plan
from src.orchestrator.revision import rappel_du_plan


@pytest.fixture(autouse=True)
def _plan_propre():
    dev_plan.clear()
    yield
    dev_plan.clear()


def test_le_rappel_nomme_letape_concernee():
    dev_plan.create(["Créer le répertoire /tmp/axon-essai",
                     "Créer le fichier tri.py avec la fonction trier_liste"])

    rappel = rappel_du_plan(["/tmp/axon-essai/tri.py"])

    assert "étape 2" in rappel
    assert "tri.py" in rappel
    assert "dev_plan_step_done" in rappel


def test_le_rappel_ne_coche_rien():
    """C'est toute la différence : il informe, il ne tranche pas."""
    dev_plan.create(["Créer le fichier tri.py"])

    rappel_du_plan(["/tmp/tri.py"])

    assert not dev_plan.steps[0].done


def test_une_etape_qui_demande_plusieurs_fichiers_est_signalee_sans_etre_close():
    """Écrire main.py n'achève pas « main.py ET utils.py »."""
    dev_plan.create(["Mettre à jour les imports dans main.py et utils.py"])

    rappel = rappel_du_plan(["/projet/main.py"])

    assert "étape 1" in rappel
    assert "sinon poursuis" in rappel
    assert not dev_plan.steps[0].done


def test_un_fichier_sans_rapport_ne_dit_rien():
    dev_plan.create(["Créer le fichier tri.py"])

    assert rappel_du_plan(["/tmp/inconnu.py"]) == ""


def test_une_etape_deja_close_nest_pas_rappelee():
    dev_plan.create(["Créer tri.py", "Tester tri.py"])
    dev_plan.check(0)

    rappel = rappel_du_plan(["/tmp/tri.py"])

    assert "étape 1" not in rappel
    assert "étape 2" in rappel


def test_sans_plan_le_rappel_est_vide():
    assert rappel_du_plan(["/tmp/tri.py"]) == ""


def test_plusieurs_etapes_concernees_sont_toutes_nommees():
    dev_plan.create(["Créer tri.py", "Documenter tri.py"])

    rappel = rappel_du_plan(["/tmp/tri.py"])

    assert "étape 1" in rappel and "étape 2" in rappel
