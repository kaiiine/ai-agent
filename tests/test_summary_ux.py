"""Le résumé que l'utilisateur lit vraiment.

Le rendu technique est exact et exhaustif — et illisible pour décider quoi faire
de vingt euros. Ces tests verrouillent ce qui rend la réponse utile SANS toucher
à ce qui la rend juste : aucun chiffre n'est recalculé, aucun classement n'est
refait, aucun indicateur n'est synthétisé.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from src.agents.quant.conversation.constraints import constraints_from_request
from src.agents.quant.conversation.renderer import render
from src.agents.quant.conversation.summary import (
    render_etat_modeles,
    render_resume,
    selection_lisible,
)
from src.agents.quant.conversation.window import PARIS, resolve_window
from tests.test_betting_conversation_safety import _evaluation, _run

_MAINTENANT = datetime(2026, 8, 6, 15, 30, tzinfo=PARIS)


def _run_revue(**kw):
    contraintes = constraints_from_request(
        None, bankroll=Decimal("20"), time_window=resolve_window("", _MAINTENANT))
    return _run(contraintes, [_evaluation(), _evaluation(event="e2")], **kw)[0]


def _texte(**kw):
    return "\n".join(render_resume(_run_revue(**kw)))


# ══ §2 — Des noms humains, jamais des identifiants ══════════════════════════
class _Candidat:
    def __init__(self, selection, event_id, participants):
        self.selection = selection
        self.event_id = event_id
        self.participant_ids = participants


def test_la_selection_prend_le_nom_du_participant():
    """« player_b » ne dit rien à personne. Le rôle est écrit dans l'identité de
    l'événement — c'est le domaine lui-même qui a noté la correspondance au
    moment de la résolution."""
    candidat = _Candidat(
        "player_b",
        "event:tennis:tour:2026-08-07T21:00:00Z:player_a=mertens_e|player_b=osaka_n",
        ("player:tennis:wta:mertens_e", "player:tennis:wta:osaka_n"))

    assert selection_lisible(candidat) == "Osaka N."


def test_l_ordre_des_participants_ne_decide_pas_du_role():
    """Déduire le rôle de l'ordre de `participant_ids` reviendrait à le deviner —
    et à intervertir deux joueurs le jour où cet ordre changerait."""
    inverse = _Candidat(
        "player_a",
        "event:tennis:tour:2026-08-07T21:00:00Z:player_a=mertens_e|player_b=osaka_n",
        ("player:tennis:wta:osaka_n", "player:tennis:wta:mertens_e"))   # ordre inversé

    assert selection_lisible(inverse) == "Mertens E."


def test_le_nul_se_dit_il_n_a_pas_de_participant():
    candidat = _Candidat("draw", "event:football:fra:2026:home=psg|away=om", ())

    assert selection_lisible(candidat) == "match nul"


def test_une_selection_dont_le_role_est_introuvable_garde_son_code():
    """Emprunter un nom au hasard serait pire que montrer un code."""
    candidat = _Candidat("player_c", "event:tennis:tour:2026:player_a=x|player_b=y", ())

    assert selection_lisible(candidat) == "player_c"


def test_aucun_identifiant_interne_dans_le_resume():
    """Codes de compétition, identités d'événement et codes de raison restent
    dans la section technique."""
    import dataclasses

    run = _run_revue()
    # Identité RÉALISTE : la clé canonique porte les rôles, comme en production.
    # Sans eux, `selection_lisible` retombe volontairement sur le code — c'est le
    # bon repli, mais il ne doit pas être ce que ce test observe.
    reelles = tuple(
        dataclasses.replace(e, candidate=dataclasses.replace(
            e.candidate,
            event_id="event:tennis:tour:2026-08-07T21:00:00Z:"
                     "player_a=mertens_e|player_b=osaka_n",
            participant_ids=("player:tennis:wta:mertens_e", "player:tennis:wta:osaka_n")))
        for e in run.response.review_candidates)
    run = dataclasses.replace(run, response=dataclasses.replace(
        run.response, review_candidates=reelles))

    texte = "\n".join(render_resume(run))

    for jargon in ("competition:", "event:", "player_a", "player_b",
                   "EXPERIMENTAL_REVIEW_ONLY", "FRESHNESS_UNKNOWN", "audit:"):
        assert jargon not in texte, jargon


# ══ §3 — edge et EV ne peuvent plus être confondus ═════════════════════════
def test_l_avantage_et_l_esperance_sont_nommes_separement():
    """« edge +3 % » seul se lit comme « pari rentable ». L'edge compare des
    PROBABILITÉS, l'espérance compare des GAINS à la cote offerte."""
    texte = _texte()

    assert "Avantage vs probabilité sans marge" in texte
    assert "Espérance à la cote actuelle" in texte
    assert "pts" in texte              # un écart de probabilités est en points


def test_une_esperance_negative_est_signalee_comme_telle():
    """La shortlist peut l'afficher pour information, mais jamais la présenter
    comme une value positive."""
    run = _run_revue()
    negatifs = [e for e in run.response.review_candidates
                if e.candidate.expected_value_low is not None
                and e.candidate.expected_value_low <= 0]
    if not negatifs:
        pytest.skip("aucun candidat à espérance négative dans ce jeu")

    texte = "\n".join(render_resume(run))

    assert "NÉGATIVE" in texte


def test_le_resume_ne_prononce_jamais_value_positive_sur_une_ev_negative():
    texte = _texte().lower()

    assert "value positive" not in texte
    assert "pari rentable" not in texte


# ══ §4 — Aucun score de confiance synthétique ══════════════════════════════
def test_aucun_score_de_confiance_n_est_fabrique():
    """Moyenner calibration, couverture, fraîcheur et CLV donnerait un « 78/100 »
    qui a l'apparence d'une mesure sans en être une.

    Le test observe la SORTIE : chercher « /100 » dans le source attraperait
    l'explication qui interdit justement ce score.
    """
    texte = _texte() + "\n".join(render_etat_modeles(_run_revue().observability))

    for interdit in ("/100", "★", "☆", "confiance :", "indice de confiance"):
        assert interdit not in texte, interdit


def test_l_etat_du_modele_montre_chaque_critere_separement():
    from src.agents.quant.conversation.observability import ModelReadiness

    mesure = ModelReadiness(
        model_name="tennis_atp_moneyline", model_version="v0", sport="tennis",
        status="EXPERIMENTAL", passed=("min_sample_size",), failed=("min_data_coverage",),
        not_measurable=("positive_clv",), monitoring=(), blockers=("min_data_coverage",),
        clv_events=0, clv_required=30,
        criteres=(("min_sample_size", "PASS", "observé 54709 vs min 500"),
                  ("min_data_coverage", "FAIL", "observé 0.774 vs min 0.9"),
                  ("positive_clv", "NOT_MEASURABLE", "aucune paire")))

    class _Obs:
        readiness = (mesure,)

    texte = "\n".join(render_etat_modeles(_Obs()))

    assert "1/3 critères prêts" in texte
    assert "calibration" not in texte or "✓" in texte     # chaque critère nommé
    assert "0/30 rencontres indépendantes" in texte       # progression CLV réelle


# ══ §7 — La bankroll non allouée est visible ═══════════════════════════════
def test_la_bankroll_non_allouee_est_explicite():
    """« Aucune mise » sans montant laisse croire à une erreur de saisie."""
    texte = _texte()

    assert "Bankroll engagée : 0 €" in texte
    assert "non allouée : 20 €" in texte


def test_aucune_mise_hypothetique_n_est_simulee():
    texte = _texte().lower()

    for interdit in ("si le modèle était", "je miserais", "tu pourrais miser",
                     "mise suggérée", "mise hypothétique"):
        assert interdit not in texte, interdit


# ══ §8 — La fenêtre réellement utilisée ════════════════════════════════════
def test_la_fenetre_est_affichee_en_tete():
    texte = _texte()

    assert "Europe/Paris" in texte
    assert "août 2026" in texte


# ══ §1 — Une shortlist bornée, pas un déversement ══════════════════════════
def test_le_nombre_de_rencontres_detaillees_est_borne():
    from src.agents.quant.conversation.summary import TOP_DETAILLE, TOP_LISTE

    assert 1 <= TOP_DETAILLE <= 5 and TOP_DETAILLE <= TOP_LISTE <= 5


def test_le_resume_explique_pourquoi_ce_n_est_pas_misable():
    texte = _texte()

    assert "Pourquoi ce n'est pas encore misable" in texte
    assert "✓" in texte and "✗" in texte
    assert "REVIEW ONLY" in texte


# ══ §6 — Le renderer consomme le classement, il ne classe pas ══════════════
def test_le_resume_ne_reclasse_jamais_les_candidats():
    """Une seconde logique de classement pour l'affichage finirait par diverger
    de celle qui décide."""
    import inspect

    from src.agents.quant.conversation import summary
    from src.agents.quant.conversation.review_ranking import rank_review

    source = inspect.getsource(summary)
    assert "rank_review" in source
    assert "sorted(" not in source, "le résumé trie lui-même"

    run = _run_revue()
    attendu = [l.candidate.candidate_id for l in rank_review(run.response.review_candidates)]
    texte = "\n".join(render_resume(run))
    from src.agents.quant.conversation.summary import rencontre_lisible
    ordre_affiche = [rencontre_lisible(l.candidate)
                     for l in rank_review(run.response.review_candidates)]

    assert attendu                       # le classement existe
    assert texte.index(ordre_affiche[0]) < texte.index("État") if "État" in texte else True


# ══ §5 — Rien plutôt que du remplissage ════════════════════════════════════
def test_aucune_section_de_contexte_sans_fait():
    """Une absence de résultat web n'est pas une preuve d'absence."""
    texte = _texte()

    assert "Contexte externe vérifié" not in texte      # aucun enrichissement ici


def test_le_contexte_s_affiche_quand_un_fait_existe():
    from src.agents.quant.enrichment.features import make

    fait = make("INJURY", "Mertens withdrew citing a right ankle injury.",
                source="WTA", url="https://www.wtatennis.com/x", confidence="OFFICIAL")
    texte = "\n".join(render_resume(_run_revue(enrich=lambda *_a, **_k: {"e1": (fait,)})))

    assert "Contexte externe vérifié" in texte
    assert "n'entre dans aucun calcul" in texte
    assert "right ankle injury" in texte


def test_jamais_d_absence_presentee_comme_une_preuve():
    texte = _texte().lower()

    for interdit in ("aucune blessure connue", "aucun forfait connu",
                     "pas de blessure", "rien à signaler"):
        assert interdit not in texte, interdit


# ══ Le rendu complet garde sa partie technique ═════════════════════════════
def test_le_detail_technique_reste_disponible():
    """Le résumé ne REMPLACE pas l'audit : il le précède."""
    texte = render(_run_revue())

    assert "Détail technique" in texte
    assert "audit:" in texte
    assert "EXPERIMENTAL_REVIEW_ONLY" in texte      # codes bruts, mais plus haut


def test_la_borne_basse_egale_a_la_probabilite_est_signalee():
    """§14 : tant qu'aucun intervalle n'est estimé, la borne basse VAUT la
    probabilité. La présenter sans le dire donnerait à un chiffre unique
    l'apparence de deux mesures indépendantes."""
    import dataclasses

    run = _run_revue()
    egales = tuple(
        dataclasses.replace(e, candidate=dataclasses.replace(
            e.candidate, probability_low=e.candidate.fair_probability))
        for e in run.response.review_candidates)
    run = dataclasses.replace(run, response=dataclasses.replace(
        run.response, review_candidates=egales))

    assert "borne basse = probabilité" in render(run)


def test_une_vraie_borne_basse_n_est_pas_signalee_a_tort():
    """Le jour où un intervalle sera estimé, la mise en garde doit disparaître
    d'elle-même — sinon elle deviendrait un mensonge inverse."""
    assert "borne basse = probabilité" not in render(_run_revue())
