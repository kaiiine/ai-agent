"""Demander une information, ce n'est pas demander la permission.

Vécu, sur « place-toi dans /tmp/axon-essai et supprime tout ce qu'il contient » :

    Confirmez-vous la suppression de tous les fichiers … ?
      ▶ Oui, supprime tout / Non, annule          ← ask_clarification
    Commande DESTRUCTIVE : rm -rf /tmp/axon-essai/*
      ▶ Oui, exécuter / Non, annuler              ← la vraie barrière

Deux questions pour un seul geste, et la première ne décidait rien : quelle que
soit la réponse, la seconde arrivait. AXON garde lui-même tout ce qui engage.

On reconnaît la demande d'autorisation à sa FORME — un couple oui/non — pas à son
texte : une formulation nouvelle ne doit pas passer entre les mailles.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.agents.clarify.permission import demande_une_permission
from src.orchestrator import clarification


@pytest.mark.parametrize("choix", [
    ["Oui, supprime tout", "Non, annule"],
    ["Non, annuler", "Oui, exécuter"],
    ["yes", "no"],
    ["Vas-y", "Stop"],
    ["D'accord", "Annuler"],
])
def test_un_couple_oui_non_est_une_demande_dautorisation(choix):
    assert demande_une_permission(choix)


@pytest.mark.parametrize("choix", [
    ["50 €", "100 €", "200 €"],          # une valeur
    ["Python 3", "Python 2"],            # un vrai choix binaire
    ["Nom court", "Nom complet"],
    [],                                   # question ouverte
    ["Oui", "Oui mais plus tard"],       # pas de négatif
])
def test_un_vrai_choix_nest_pas_refuse(choix):
    assert not demande_une_permission(choix)


@pytest.fixture
def poser(monkeypatch):
    """Fait passer un appel `ask_clarification` par l'orchestrateur.

    Rend (charge du résultat, nombre de questions réellement posées).
    """
    posees: list = []
    monkeypatch.setattr(clarification, "demander",
                        lambda d: (posees.append(d), [q.texte for q in d.questions])[1])

    def _poser(questions):
        etat = {"messages": [AIMessage("", tool_calls=[
            {"name": "ask_clarification", "id": "c1", "args": {"questions": questions}}])]}
        sortie = clarification.clarifier_appel(etat)
        return json.loads(sortie["messages"][0].content), len(posees)
    return _poser


def test_la_confirmation_natteint_pas_lutilisateur(poser):
    charge, posees = poser([{"question": "Confirmez-vous la suppression ?",
                             "choices": ["Oui, supprime tout", "Non, annule"]}])

    assert posees == 0, "l'utilisateur a été dérangé pour rien"
    assert charge["status"] == "ok"


def test_le_filet_ne_sannonce_pas_comme_un_echec(poser):
    """Le journal peint en rouge tout résultat portant `"status": "error"`, et
    l'utilisateur voyait « Question refusée » deux fois pour un seul geste. Ce que
    le modèle ne devrait pas demander se règle dans son prompt, pas à l'écran."""
    import json as _json

    charge, _ = poser([{"question": "Je supprime ?", "choices": ["Oui", "Non"]}])
    texte = _json.dumps(charge, ensure_ascii=False)

    assert '"status": "error"' not in texte
    assert "refus" not in texte.lower()


def test_le_modele_est_invite_a_poursuivre(poser):
    charge, _ = poser([{"question": "Je supprime ?", "choices": ["Oui", "Non"]}])

    assert "continue" in charge["message"].lower()
    assert "au moment d'agir" in charge["message"]


def test_une_information_manquante_passe_toujours(poser):
    charge, posees = poser([{"question": "Quelle bankroll ?",
                             "choices": ["50 €", "100 €", "200 €"]}])

    assert posees == 1
    assert "answers" in charge


def test_une_question_ouverte_passe_toujours(poser):
    _, posees = poser([{"question": "Quel nom pour le module ?"}])

    assert posees == 1


def test_un_lot_mixte_passe_par_le_filet(poser):
    """Servir la moitié d'un lot laisserait l'appel sans résultat complet."""
    charge, posees = poser([
        {"question": "Quel nom ?", "choices": []},
        {"question": "Je supprime ?", "choices": ["Oui", "Non"]}])

    assert posees == 0
    assert charge["status"] == "ok"


def test_le_filet_couvre_aussi_loutil_execute():
    """L'agent de code exécute l'outil pour de vrai, sans passer par le nœud."""
    from src.agents.clarify.tools import ask_clarification

    charge = json.loads(ask_clarification.invoke({"questions": [
        {"question": "Je supprime ?", "choices": ["Oui", "Non"]}]}))

    assert charge["status"] == "ok"


# ── la vraie correction est en amont : le prompt l'ordonnait ──────────────────
def test_le_prompt_nordonne_plus_de_confirmer_avant():
    """« Confirm before any irreversible action (deletion, sending, push) » et
    « Confirm before: rm, git reset --hard, … any deletion » : le modèle obéissait.
    Le garde-fou se battait contre la consigne au lieu de la lever."""
    from src.llm.prompts import orchestrateur

    source = Path(orchestrateur.__file__).read_text(encoding="utf-8")

    assert "Confirm before any irreversible action" not in source
    assert "Confirm before: rm" not in source


def test_le_prompt_dit_ou_est_la_vraie_barriere():
    from src.llm.prompts import orchestrateur

    source = Path(orchestrateur.__file__).read_text(encoding="utf-8")

    assert "AXON asks for consent ITSELF" in source
    assert "never call ask_clarification with yes/no choices" in source
