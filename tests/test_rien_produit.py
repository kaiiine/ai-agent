"""Décrire le travail n'est pas le faire.

Vécu : le modèle a rendu son plan dans `dev_explain`, puis le fichier ENTIER en
texte — sans jamais appeler `propose_file_change`. Aucun plan n'ayant été créé,
la règle « conclure si le plan est achevé » était satisfaite d'office, et le run
se terminait sur une réponse en prose. L'utilisateur voyait du code, et rien sur
le disque.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from src.agents.coding.pending import dev_plan
from src.agents.coding.specialist import _relances, interpreter_reponse


@pytest.fixture(autouse=True)
def _run_neuf():
    dev_plan.clear()
    _relances.update({"texte": 0, "outils": 0, "skill": False,
                      "produit": False, "vide": 0})
    yield
    dev_plan.clear()


def _appel(nom: str) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": nom, "id": "x", "args": {}}])


def test_conclure_sans_rien_avoir_ecrit_est_relance():
    interpreter_reponse(_appel("dev_explain"), [], {"dev_explain": None}, "écris un script")

    _, fini, rappel = interpreter_reponse(
        AIMessage("#!/usr/bin/env python3\nprint(1)"), [], {}, "écris un script")

    assert not fini
    assert "RIEN écrit" in rappel
    assert "propose_file_change" in rappel


def test_la_relance_ne_se_repete_pas():
    """Insister sans fin ne vaut pas mieux que céder trop vite."""
    interpreter_reponse(AIMessage("du texte"), [], {}, "écris un script")
    _, fini, _ = interpreter_reponse(AIMessage("encore du texte"), [], {}, "écris un script")

    assert fini


@pytest.mark.parametrize("outil", ["propose_file_change", "edit_file", "shell_run",
                                   "propose_file_delete"])
def test_un_outil_productif_debloque_la_conclusion(outil):
    interpreter_reponse(_appel(outil), [], {outil: None}, "écris un script")

    _, fini, _ = interpreter_reponse(AIMessage("c'est fait"), [], {}, "écris un script")

    assert fini


def test_dev_explain_seul_ne_compte_pas_comme_production():
    """Il décrit, il ne produit pas — c'est exactement ce qui laissait passer."""
    interpreter_reponse(_appel("dev_explain"), [], {"dev_explain": None}, "écris")

    assert not _relances["produit"]
