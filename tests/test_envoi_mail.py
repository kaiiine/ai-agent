"""L'envoi d'un mail : demandé ET exécuté par le graphe.

`review_email()` appelait `_do_send()` elle-même : le client n'affichait pas, il
AGISSAIT. Deux conséquences. Appelé par l'API, aucun mail ne partait jamais et
rien ne le disait — le brouillon restait un brouillon. Et en lisant le graphe, on
ne pouvait pas savoir qu'un mail pouvait partir : l'effet le plus irréversible
d'AXON était invisible depuis l'endroit qui décrit ce qu'il fait.
"""
from __future__ import annotations

from typing import TypedDict

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.orchestrator.envoi import (
    ANNULER,
    ENVOYER,
    MODIFIER,
    envoi_attendu,
    envoyer,
)
from src.orchestrator.hitl import ENVOI, demande_en_attente, reponse


class _Etat(TypedDict):
    messages: list


@pytest.fixture
def brouillon(monkeypatch):
    """Un brouillon en attente, et un compteur d'envois RÉELS."""
    from src.agents.gmail import tools as gmail

    gmail._draft.update({"to": "a@b.c", "subject": "Objet", "body": "Corps",
                         "cc": None, "bcc": None, "has_draft": True})
    envois: list[str] = []
    monkeypatch.setattr(gmail, "_do_send",
                        lambda: (envois.append("envoyé"), "Mail envoyé.")[1])
    yield envois
    gmail._vider_brouillon()


def _resultat_outil(nom="gmail_send_email"):
    return ToolMessage(content="brouillon prêt", tool_call_id="tc", name=nom)


def _graphe():
    g = StateGraph(_Etat)
    g.add_node("envoyer", envoyer)
    g.add_edge(START, "envoyer")
    g.add_edge("envoyer", END)
    return g.compile(checkpointer=MemorySaver())


# ── Quand demander ───────────────────────────────────────────────────────────
def test_un_brouillon_pret_declenche_la_demande(brouillon):
    assert envoi_attendu({"messages": [_resultat_outil()]})


def test_un_autre_outil_ne_declenche_rien(brouillon):
    assert not envoi_attendu({"messages": [_resultat_outil("shell_run")]})
    assert not envoi_attendu({"messages": [AIMessage(content="texte")]})
    assert not envoi_attendu({"messages": []})


def test_sans_brouillon_rien_ne_se_declenche():
    from src.agents.gmail import tools as gmail
    gmail._vider_brouillon()
    assert not envoi_attendu({"messages": [_resultat_outil()]})


# ── Ce qui est montré ────────────────────────────────────────────────────────
def test_le_destinataire_l_objet_et_le_CORPS_sont_montres(brouillon):
    """Approuver un mail sans voir son corps, c'est approuver un texte inconnu
    envoyé en son nom."""
    app = _graphe()
    cfg = {"configurable": {"thread_id": "montre"}}
    demande = demande_en_attente(app.invoke({"messages": [_resultat_outil()]}, cfg))

    assert demande.genre == ENVOI
    assert "a@b.c" in demande.apercu
    assert "Objet" in demande.apercu
    assert "Corps" in demande.apercu
    assert demande.questions[0].affirmatif == ENVOYER


# ── Les trois issues ─────────────────────────────────────────────────────────
def test_envoyer_envoie_UNE_fois(brouillon):
    """Le rejeu du nœud est la raison d'être de ce test : un envoi placé avant
    l'interruption partirait deux fois, et un mail ne se rattrape pas."""
    app = _graphe()
    cfg = {"configurable": {"thread_id": "envoi"}}
    app.invoke({"messages": [_resultat_outil()]}, cfg)
    finale = app.invoke(reponse([ENVOYER, ""]), cfg)

    assert brouillon == ["envoyé"], f"envois : {brouillon}"
    assert "envoyé" in finale["messages"][-1].content.lower()


def test_annuler_n_envoie_rien_et_vide_le_brouillon(brouillon):
    from src.agents.gmail import tools as gmail

    app = _graphe()
    cfg = {"configurable": {"thread_id": "annule"}}
    app.invoke({"messages": [_resultat_outil()]}, cfg)
    app.invoke(reponse([ANNULER, ""]), cfg)

    assert brouillon == []
    assert not gmail._draft["has_draft"], (
        "un brouillon refusé qui reste en attente relancerait la demande au "
        "tour suivant")
    assert gmail._draft["body"] is None, (
        "les champs doivent partir avec : un contenu refusé ne doit rester "
        "lisible par rien")


def test_modifier_n_envoie_rien_et_transmet_la_demande(brouillon):
    app = _graphe()
    cfg = {"configurable": {"thread_id": "modifie"}}
    app.invoke({"messages": [_resultat_outil()]}, cfg)
    finale = app.invoke(reponse([MODIFIER, "sois plus bref"]), cfg)

    assert brouillon == []
    assert "plus bref" in finale["messages"][-1].content


@pytest.mark.parametrize("decision", ["", "envoyer", "oui", "n'importe quoi"])
def test_seul_le_libelle_exact_envoie(brouillon, decision):
    """Un client en panne, une fenêtre fermée ou une casse différente ne doivent
    pas expédier un mail au nom de l'utilisateur."""
    app = _graphe()
    cfg = {"configurable": {"thread_id": f"strict-{decision or 'vide'}"}}
    app.invoke({"messages": [_resultat_outil()]}, cfg)
    app.invoke(reponse([decision, ""]), cfg)

    assert brouillon == [], f"« {decision} » a envoyé le mail"
