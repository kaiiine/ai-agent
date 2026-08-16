"""Une sélection de valeur n'est pas un pronostic — et l'affichage le laissait croire.

Le moteur classe par espérance, pas par probabilité ([advisor/ranking/sort.py]) :
`predict_selections` rend les DEUX camps avec p et 1-p, et le classement remonte
celui dont l'écart au prix est le meilleur. Une sélection peut donc arriver en
tête avec 47,60 % — le modèle donne alors l'autre camp gagnant à 52,40 %.

Affiché sous un intitulé « sél. » avec sa probabilité à côté, ça se lit « qui va
gagner ». Sur trois lignes d'un scan réel, deux avaient sélection = favori et une
non : rien ne signalait le changement de nature, et le pari est parti à l'envers.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.agents.quant.conversation.renderer import _avertissement_selection_perdante


class _Candidat:
    """Porte les mêmes dérivations que le domaine — le renderer ne calcule rien."""

    def __init__(self, p: str, n_participants: int = 2):
        self.fair_probability = Decimal(p)
        self.participant_ids = tuple(f"p{i}" for i in range(n_participants))

    @property
    def donnee_perdante(self) -> bool:
        return self.fair_probability < Decimal("0.5")

    @property
    def probabilite_complementaire(self) -> Decimal:
        return Decimal("1") - self.fair_probability


def test_une_selection_sous_50_est_annoncee_perdante():
    ligne = _avertissement_selection_perdante(_Candidat("0.4760"))[0]

    assert "PERDANTE" in ligne
    assert "47.60 %" in ligne


def test_le_complement_est_donne_pour_que_le_lecteur_situe_le_favori():
    """Sans le 52,40 %, il faut faire la soustraction de tête."""
    assert "52.40 %" in _avertissement_selection_perdante(_Candidat("0.4760"))[0]


def test_la_raison_du_classement_est_dite():
    """« Pourquoi est-elle en tête si elle est perdante ? » doit être répondu là."""
    ligne = _avertissement_selection_perdante(_Candidat("0.4760"))[0]

    assert "cote la sous-évalue" in ligne
    assert "pas parce qu'elle est probable" in ligne


def test_un_favori_ne_declenche_aucun_avertissement():
    """Deux lignes sur trois du scan réel étaient dans ce cas : les alerter
    toutes banaliserait la marque."""
    assert _avertissement_selection_perdante(_Candidat("0.5895")) == []


def test_exactement_50_pourcent_n_est_pas_perdant():
    assert _avertissement_selection_perdante(_Candidat("0.5")) == []


def test_sur_un_marche_a_trois_issues_aucun_camp_n_est_nomme():
    """Le complément se répartit sur plusieurs issues : parler de « l'autre camp »
    serait faux sur un 1X2."""
    ligne = _avertissement_selection_perdante(_Candidat("0.40", n_participants=3))[0]

    assert "autre camp" not in ligne
    assert "2 autres issues" in ligne


def test_l_avertissement_vit_dans_la_sortie_structuree():
    """Écrit en aval par un résumé, il pourrait être omis. Écrit ici, il fait
    partie de ce que le moteur produit."""
    import inspect

    from src.agents.quant.conversation import renderer

    source = inspect.getsource(renderer._render_candidat)

    assert "_avertissement_selection_perdante" in source


@pytest.mark.parametrize("attendu", ["sél. VALEUR", "n'est pas un pronostic"])
def test_le_tableau_ne_promet_plus_un_pronostic(attendu):
    import inspect

    from src.agents.quant.conversation import renderer

    assert attendu in inspect.getsource(renderer._render_revue)


def test_la_ligne_de_tableau_marque_les_selections_perdantes():
    import inspect

    from src.agents.quant.conversation import renderer

    source = inspect.getsource(renderer._render_ligne_revue)

    assert "donnee_perdante" in source and "marque" in source


def test_les_deux_derivations_vivent_dans_le_domaine():
    """`test_le_renderer_ne_derive_aucun_montant_lui_meme` interdit à la
    présentation de définir un chiffre : au premier arrondi divergent, l'utilisateur
    lirait une valeur que l'Advisor n'a jamais calculée."""
    from src.agents.quant.advisor.domain.candidates import CandidateBet

    assert isinstance(CandidateBet.donnee_perdante, property)
    assert isinstance(CandidateBet.probabilite_complementaire, property)


# ── Péremption des notes Elo ────────────────────────────────────────────────
# Les six joueurs du scan du 12 août avaient entre 34 et 43 jours d'ancienneté :
# le jeu de données est une fixture figée, et rien ne le signalait.

def test_le_seuil_de_peremption_est_plus_court_qu_un_mois():
    from src.agents.quant.betting_engine.sports.tennis.live_model import PEREMPTION_JOURS

    assert 7 <= PEREMPTION_JOURS <= 30


def test_l_anciennete_des_notes_est_calculable_par_joueur():
    from src.agents.quant.betting_engine.sports.tennis.live_model import _dernier_match

    vu = _dernier_match("atp")

    assert vu, "aucune date de dernier match : la péremption serait invisible"
    assert all(hasattr(d, "year") for d in list(vu.values())[:5])


def test_le_modele_avertit_quand_les_notes_sont_perimees():
    import inspect

    from src.agents.quant.betting_engine.sports.tennis import live_model

    source = inspect.getsource(live_model.TennisMoneylineModel.predict_selections)

    assert "PEREMPTION_JOURS" in source
    assert "PÉRIMÉES" in source
    assert "anciennete_notes_jours" in source, "l'âge doit être une feature lisible"
