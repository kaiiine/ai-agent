"""La question est posée par le GRAPHE, pas demandée au modèle.

Vécu, sur backend Gemini : « Tu me conseillerais quoi comme combiné ? » appelait
`betting_recommend`, qui n'avait pas de bankroll. Le résultat portait la consigne
« À FAIRE MAINTENANT : appelle `ask_clarification` », arrivée intacte jusqu'au
modèle — vérifié dans le panneau de debug. Le modèle a répondu en prose et rendu
la main.

Deux vérifications ont écarté les causes faciles : `ask_clarification` est dans
`_PINNED_TOOLS` et figurait bien dans les outils liés, et son schéma imbriqué
survit intact à la conversion Gemini. L'outil était disponible et appelable.

Le défaut était le MÉCANISME. Le questionnaire ne peut pas se déclencher sans un
vrai appel d'outil — la reprise a besoin d'un `tool_call_id` pour remplacer le
`ToolMessage` par les réponses. Demander cet appel par du texte, c'est faire
dépendre un mécanisme déterministe d'une obéissance probabiliste.

Or la condition est calculable : `missing()` rend les champs absents. Le graphe
émet donc l'appel lui-même, identiquement sur tous les backends.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.orchestrator.clarification import (
    QUESTIONS,
    apres_les_outils,
    champs_manquants,
    clarifier,
    deja_demande,
)


def _resultat(statut="CLARIFICATION_REQUIRED", missing=("bankroll",), nom="betting_recommend"):
    return ToolMessage(
        content=json.dumps({"status": statut, "missing": list(missing),
                            "rendered": "peu importe"}),
        tool_call_id="tc-1", name=nom)


# ── Le contrat entre l'outil et le graphe ────────────────────────────────────
def test_l_outil_nomme_les_champs_qui_manquent():
    """Le graphe ne redérive pas `missing()` : il le lit. Dupliquer la règle la
    ferait diverger au premier champ obligatoire ajouté."""
    from src.agents.quant.conversation.constraints import UserBettingConstraints

    assert UserBettingConstraints().missing() == ("bankroll",)
    assert "bankroll" in QUESTIONS, "champ obligatoire sans question associée"


def test_un_champ_sans_question_connue_est_ecarte():
    """Mieux vaut laisser le modèle expliquer le manque qu'ouvrir un
    questionnaire dont l'intitulé serait un nom de variable."""
    assert champs_manquants(_resultat(missing=["champ_inconnu"])) == ()


@pytest.mark.parametrize("statut", ["COMPLETED", "EMPTY_WINDOW", "TECHNICAL_FAILURE"])
def test_les_autres_statuts_ne_declenchent_rien(statut):
    assert champs_manquants(_resultat(statut=statut)) == ()
    assert apres_les_outils({"messages": [_resultat(statut=statut)]}) == "chatbot"


def test_un_resultat_qui_n_est_pas_du_json_ne_casse_rien():
    brut = ToolMessage(content="texte libre", tool_call_id="tc-1", name="shell_run")
    assert champs_manquants(brut) == ()
    assert apres_les_outils({"messages": [brut]}) == "chatbot"


# ── L'appel émis ─────────────────────────────────────────────────────────────
def test_le_graphe_route_vers_le_noeud_de_clarification():
    assert apres_les_outils({"messages": [_resultat()]}) == "clarifier"


def test_le_noeud_emet_un_VRAI_appel_d_outil():
    """Le cœur du correctif. Un texte, si impératif soit-il, ne porte pas de
    `tool_call_id` — donc rien à reprendre, donc pas de questionnaire."""
    [message] = clarifier({"messages": [_resultat()]})["messages"]

    assert isinstance(message, AIMessage)
    assert len(message.tool_calls) == 1
    appel = message.tool_calls[0]
    assert appel["name"] == "ask_clarification"
    assert appel["id"], "sans identifiant, la reprise ne peut pas recoller la réponse"

    [question] = appel["args"]["questions"]
    assert "bankroll" in question["question"].lower()
    assert question["choices"], "un questionnaire sans choix demande de taper un montant"


def test_les_choix_proposes_n_incluent_pas_Autre():
    """L'interface l'ajoute elle-même ; le doubler afficherait deux « Autre »."""
    for champ, q in QUESTIONS.items():
        libelles = " ".join(q.get("choices") or []).lower()
        assert "autre" not in libelles, f"« Autre » codé en dur pour {champ}"


# ── La garde anti-boucle ─────────────────────────────────────────────────────
def test_on_ne_repose_pas_une_question_deja_posee():
    """Sans cette garde, un modèle qui rappelle l'outil sans reporter la réponse
    relance le questionnaire indéfiniment. Un correctif qui boucle est pire que
    le défaut qu'il corrige : le défaut, lui, rendait la main."""
    deja = ToolMessage(
        content=json.dumps({"questions": [{"question": QUESTIONS["bankroll"]["question"]}],
                            "awaiting_input": True}),
        tool_call_id="tc-0", name="ask_clarification")

    assert deja_demande([deja], ("bankroll",))
    assert apres_les_outils({"messages": [deja, _resultat()]}) == "chatbot"


def test_une_reponse_deja_donnee_clot_le_sujet():
    """Les réponses portent la clé `answers` : leur présence suffit à dire qu'on
    a déjà interrogé l'utilisateur sur ce fil."""
    repondu = ToolMessage(content=json.dumps({"answers": {"bankroll": "100 €"}}),
                          tool_call_id="tc-0", name="ask_clarification")

    assert deja_demande([repondu], ("bankroll",))
    assert apres_les_outils({"messages": [repondu, _resultat()]}) == "chatbot"


def test_un_questionnaire_sur_un_AUTRE_sujet_ne_bloque_pas():
    """La garde doit reconnaître les questions posées, pas museler toute
    clarification dès qu'il y en a eu une."""
    autre = ToolMessage(
        content=json.dumps({"questions": [{"question": "Quel sport veux-tu suivre ?"}]}),
        tool_call_id="tc-0", name="ask_clarification")

    assert not deja_demande([autre], ("bankroll",))


# ── Un seul mécanisme, pas deux ──────────────────────────────────────────────
def test_le_texte_ne_reclame_plus_l_appel_lui_meme():
    """La consigne texte a été mesurée SANS effet. La laisser à côté du mécanisme
    qui marche ferait croire qu'elle y participe, et le prochain lecteur
    chercherait la garantie du mauvais côté."""
    from src.agents.quant.conversation.constraints import UserBettingConstraints
    from src.agents.quant.conversation.recommend import (
        CLARIFICATION_REQUIRED,
        RecommendationRun,
    )
    from src.agents.quant.conversation.renderer import _render_echec

    rendu = _render_echec(RecommendationRun(
        CLARIFICATION_REQUIRED, UserBettingConstraints(), detail="bankroll requise"))
    assert "ask_clarification" not in rendu


def test_le_graphe_declare_le_noeud_et_ses_aretes():
    """Le module peut être parfait et n'être jamais appelé."""
    import inspect

    from src.orchestrator import graph as g

    source = inspect.getsource(g)
    assert 'g.add_node("clarifier"' in source
    assert 'g.add_conditional_edges("tools", apres_les_outils' in source
    assert 'g.add_edge("clarifier", "tools")' in source, (
        "le questionnaire doit repasser par `tools` pour produire l'attente")
