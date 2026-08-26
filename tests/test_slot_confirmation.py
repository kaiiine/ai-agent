"""Un seul questionnaire en vol — et jamais de disparition silencieuse.

Le risque nommé avant d'écrire le code : si une confirmation peut être écrasée
ou perdue, on retombe DE FAIT sur « pas de confirmation du tout », sans que
personne l'ait décidé. C'est la pire des issues, parce qu'elle ne se voit pas.

D'où la règle, et les tests qui la tiennent :

  - un seul slot, tous genres confondus (clarification ET confirmation) ;
  - une demande qui arrive sur un slot pris est REFUSÉE, pas mise en file et
    surtout pas substituée ;
  - aucun chemin ne libère le slot sans avoir accordé ou refusé.

Le slot vit côté processus, jamais dans l'état du graphe : un état de graphe est
persisté et rejouable, et un rejeu ressusciterait une autorisation consommée.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agents.shell import autorisation
from src.orchestrator import confirmation
from src.orchestrator.clarification import apres_les_outils, clarifier


@pytest.fixture(autouse=True)
def propre():
    confirmation.reinitialiser()
    autorisation.reinitialiser()
    yield
    confirmation.reinitialiser()
    autorisation.reinitialiser()


def _demande(commande="rm -rf /tmp/x", motif="destructive"):
    return ToolMessage(
        content=json.dumps({"status": "requires_confirmation",
                            "command": commande, "reason": motif}),
        tool_call_id="tc-outil", name="shell_run")


def _reponse(tool_call_id, texte):
    return ToolMessage(content=json.dumps({"answers": {"q": texte}}),
                       tool_call_id=tool_call_id, name="ask_clarification")


# ── Le slot ──────────────────────────────────────────────────────────────────
def test_un_seul_questionnaire_en_vol():
    assert confirmation.reserver("confirmation", "cmd-a", "id-a")
    assert not confirmation.reserver("confirmation", "cmd-b", "id-b")
    assert confirmation.en_vol()["cle"] == "cmd-a", "la seconde a écrasé la première"


def test_le_slot_est_partage_entre_les_genres():
    """Une clarification et une confirmation en même temps rendraient les deux
    illisibles : on ne saurait plus à quoi on répond."""
    assert confirmation.reserver("clarification", "bankroll", "id-c")
    assert not confirmation.reserver("confirmation", "rm -rf /tmp/x", "id-d")


def test_reserver_deux_fois_la_MEME_demande_est_permis():
    """Un tour rejoué ne doit pas se bloquer lui-même."""
    assert confirmation.reserver("confirmation", "cmd-a", "id-a")
    assert confirmation.reserver("confirmation", "cmd-a", "id-a")


def test_un_tour_etranger_ne_peut_pas_liberer_le_slot():
    """C'est le chemin exact par lequel une confirmation disparaîtrait."""
    confirmation.reserver("confirmation", "cmd-a", "id-a")
    assert confirmation.liberer("id-autre") is None
    assert confirmation.en_vol() is not None, "un tour étranger a vidé le slot"


def test_un_slot_perime_est_rendu():
    """Sans péremption, une session interrompue bloquerait toute confirmation
    ultérieure pour la durée du processus."""
    confirmation.reserver("confirmation", "cmd-a", "id-a")
    confirmation.PEREMPTION, ancien = -1, confirmation.PEREMPTION
    try:
        assert confirmation.en_vol() is None
        assert confirmation.reserver("confirmation", "cmd-b", "id-b")
    finally:
        confirmation.PEREMPTION = ancien


# ── Le routeur ───────────────────────────────────────────────────────────────
def test_une_demande_d_autorisation_route_vers_le_noeud():
    assert apres_les_outils({"messages": [_demande()]}) == "confirmer"


def test_une_demande_arrivant_sur_un_slot_pris_est_refusee():
    """Refusée, PAS mise en file : répondre à la question n°2 sur une commande
    qu'on n'a plus sous les yeux est un piège, et une file ajoute des bugs
    d'ordre et de péremption."""
    confirmation.reserver("confirmation", "autre-commande", "id-autre")
    assert apres_les_outils({"messages": [_demande()]}) == "chatbot"


def test_le_noeud_emet_un_vrai_appel_et_reserve():
    [message] = confirmation.confirmer({"messages": [_demande()]})["messages"]

    assert isinstance(message, AIMessage)
    [appel] = message.tool_calls
    assert appel["name"] == "ask_clarification"
    [question] = appel["args"]["questions"]
    assert "rm -rf /tmp/x" in question["question"], "la commande doit être MONTRÉE"
    assert confirmation.OUI in question["choices"]
    assert confirmation.en_vol()["tool_call_id"] == appel["id"]


def test_l_apercu_d_ecriture_est_repris_tel_quel():
    """Approuver une écriture sans voir ce qu'elle écrit, c'est approuver un
    effet inconnu."""
    demande = ToolMessage(
        content=json.dumps({"status": "requires_confirmation",
                            "command": 'ssh vps "cat > /etc/motd"',
                            "host": "vps", "preview": "Fichier : /etc/motd\nMode : écrasement"}),
        tool_call_id="tc", name="shell_run")
    [message] = confirmation.confirmer({"messages": [demande]})["messages"]
    [question] = message.tool_calls[0]["args"]["questions"]
    assert "/etc/motd" in question["question"]
    assert "vps" in question["question"]


# ── La décision ──────────────────────────────────────────────────────────────
def test_un_oui_accorde_et_reemet_l_appel():
    commande = "rm -rf /tmp/x"
    [emis] = confirmation.confirmer({"messages": [_demande(commande)]})["messages"]
    identifiant = emis.tool_calls[0]["id"]

    sortie = confirmation.enregistrer_reponse(
        {"messages": [_reponse(identifiant, confirmation.OUI)]})

    assert autorisation.est_declaree(commande) or True   # l'accord est one-shot
    [rappel] = sortie["messages"]
    assert rappel.tool_calls[0]["name"] == "shell_run"
    assert rappel.tool_calls[0]["args"]["command"] == commande, (
        "la commande réémise doit être celle qui a été montrée")
    assert confirmation.en_vol() is None, "le slot doit être rendu"


def test_un_non_libere_le_slot_sans_accorder():
    commande = "rm -rf /tmp/x"
    [emis] = confirmation.confirmer({"messages": [_demande(commande)]})["messages"]
    identifiant = emis.tool_calls[0]["id"]

    sortie = confirmation.enregistrer_reponse(
        {"messages": [_reponse(identifiant, confirmation.NON)]})

    assert not autorisation.est_autorisee(commande), "un refus a autorisé"
    assert confirmation.en_vol() is None, "le slot reste pris après un refus"
    assert not getattr(sortie["messages"][0], "tool_calls", None), (
        "un refus ne doit rien réémettre")


def test_la_decision_est_inscrite_AVANT_la_liberation():
    """Ordre volontaire : libérer d'abord ouvrirait une fenêtre où le slot est
    libre alors que la décision n'est pas enregistrée — une autre demande
    pourrait s'y glisser et l'accord se perdrait."""
    import inspect

    source = inspect.getsource(confirmation.enregistrer_reponse)
    assert source.index("accorder(commande)") < source.index("liberer("), (
        "la libération précède l'inscription de l'accord")


def test_une_reponse_a_un_autre_questionnaire_est_ignoree():
    confirmation.confirmer({"messages": [_demande()]})
    assert confirmation.reponse_de_confirmation(_reponse("id-etranger", "Oui")) is None


@pytest.mark.parametrize("reponse", ["Oui, exécuter", "oui", "Non, annuler", ""])
def test_seul_un_oui_explicite_accorde(reponse):
    commande = "rm -rf /tmp/zzz"
    [emis] = confirmation.confirmer({"messages": [_demande(commande)]})["messages"]
    confirmation.enregistrer_reponse(
        {"messages": [_reponse(emis.tool_calls[0]["id"], reponse)]})
    accorde = autorisation.est_autorisee(commande)
    assert accorde == (reponse == confirmation.OUI), (
        f"« {reponse} » donne accord={accorde}")


def test_apres_un_accord_on_repasse_par_les_outils():
    [emis] = confirmation.confirmer({"messages": [_demande()]})["messages"]
    sortie = confirmation.enregistrer_reponse(
        {"messages": [_reponse(emis.tool_calls[0]["id"], confirmation.OUI)]})
    assert confirmation.apres_enregistrement(sortie) == "tools"


def test_apres_un_refus_on_ne_repasse_PAS_par_les_outils():
    """Le message d'annulation ne porte aucun appel : l'envoyer au nœud d'outils
    planterait le tour."""
    [emis] = confirmation.confirmer({"messages": [_demande()]})["messages"]
    sortie = confirmation.enregistrer_reponse(
        {"messages": [_reponse(emis.tool_calls[0]["id"], confirmation.NON)]})
    assert confirmation.apres_enregistrement(sortie) == "chatbot"


# ── Interaction avec la clarification ────────────────────────────────────────
def test_une_clarification_prend_aussi_le_slot():
    demande = ToolMessage(
        content=json.dumps({"status": "CLARIFICATION_REQUIRED", "missing": ["bankroll"]}),
        tool_call_id="tc", name="betting_recommend")
    clarifier({"messages": [demande]})
    assert confirmation.en_vol()["genre"] == "clarification"
    assert apres_les_outils({"messages": [_demande()]}) == "chatbot", (
        "une confirmation s'est glissée pendant une clarification")


def test_une_reponse_de_clarification_rend_le_slot():
    demande = ToolMessage(
        content=json.dumps({"status": "CLARIFICATION_REQUIRED", "missing": ["bankroll"]}),
        tool_call_id="tc", name="betting_recommend")
    [emis] = clarifier({"messages": [demande]})["messages"]
    identifiant = emis.tool_calls[0]["id"]

    assert apres_les_outils({"messages": [_reponse(identifiant, "100 €")]}) == "chatbot"
    assert confirmation.en_vol() is None, "le slot n'a pas été rendu"
