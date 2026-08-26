"""Taire un journal tiers, sans le rendre muet à une vraie panne.

Vécu : chaque tour sur backend Gemini affichait, en plein TUI,

    Key '$schema' is not supported in schema, ignoring
    Key 'additionalProperties' is not supported in schema, ignoring

Une ligne par clé refusée, par outil, à chaque appel. `main.py` faisait déjà
taire stderr et les `warnings`, mais uniquement pendant la phase d'IMPORT — ces
journaux-là sont émis à l'exécution et passaient donc à travers.
"""
from __future__ import annotations

import io
import logging

import pytest

from src.infra.journal import _BAVARDS, taire_les_bavards


@pytest.fixture
def journal():
    """Capture ce qui sort du logger racine, et restaure les niveaux ensuite."""
    flux = io.StringIO()
    handler = logging.StreamHandler(flux)
    racine = logging.getLogger()
    racine.addHandler(handler)
    niveau_racine = racine.level
    racine.setLevel(logging.WARNING)
    avant = {nom: logging.getLogger(nom).level for nom in _BAVARDS}
    try:
        yield flux
    finally:
        racine.removeHandler(handler)
        racine.setLevel(niveau_racine)
        for nom, niveau in avant.items():
            logging.getLogger(nom).setLevel(niveau)


def test_le_bruit_du_convertisseur_gemini_est_tu(journal):
    """Le cas réel, de bout en bout : la conversion d'un outil au schéma imbriqué."""
    from langchain_google_genai._function_utils import (
        convert_to_genai_function_declarations,
    )

    from src.agents.clarify.tools import ask_clarification

    convert_to_genai_function_declarations([ask_clarification])
    assert "not supported in schema" in journal.getvalue(), (
        "le bruit a disparu tout seul — ce test ne prouve plus rien")

    journal.truncate(0)
    journal.seek(0)
    taire_les_bavards()
    convert_to_genai_function_declarations([ask_clarification])
    assert journal.getvalue() == ""


def test_une_vraie_panne_passe_toujours(journal):
    """Le niveau reste à ERROR, jamais CRITICAL ni NOTSET : taire un journal ne
    doit pas revenir à s'aveugler sur une panne du fournisseur."""
    taire_les_bavards()
    for nom in _BAVARDS:
        logging.getLogger(nom).error("panne fournisseur")
    assert journal.getvalue().count("panne fournisseur") == len(_BAVARDS)


def test_aucun_journal_n_est_tu_au_dela_de_error():
    """Garde-fou sur la table elle-même : `CRITICAL` y masquerait les erreurs."""
    for nom, niveau in _BAVARDS.items():
        assert niveau <= logging.ERROR, f"{nom} tu au-delà d'ERROR"


def test_le_schema_imbrique_survit_a_la_conversion_gemini():
    """La raison pour laquelle ce bruit est jugé inoffensif, et pas un simple
    agacement : la conversion RÉSOUT `$defs`/`$ref` avant de les jeter.

    Si un jour elle cessait de le faire, `ask_clarification` arriverait chez
    Gemini avec une liste d'objets vides — le modèle ne pourrait plus l'appeler,
    et on l'aurait tu."""
    from langchain_google_genai._function_utils import (
        convert_to_genai_function_declarations,
    )

    from src.agents.clarify.tools import ask_clarification

    [outil] = convert_to_genai_function_declarations([ask_clarification])
    [declaration] = outil.function_declarations
    questions = declaration.parameters.properties["questions"]

    assert questions.items is not None, "l'objet imbriqué a été perdu"
    assert "question" in questions.items.properties, (
        "le champ `question` a disparu du schéma envoyé à Gemini")
