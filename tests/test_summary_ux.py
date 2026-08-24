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
def test_le_resume_ne_trie_aucun_candidat_lui_meme():
    """Une seconde logique de classement pour l'affichage finirait par diverger
    de celle qui décide.

    La vérification porte sur les CANDIDATS, pas sur tout appel à `sorted` : le
    résumé ordonne légitimement des compteurs de refus, et une interdiction en
    bloc l'aurait confondu avec un reclassement.
    """
    import ast
    import inspect

    from src.agents.quant.conversation import summary

    arbre = ast.parse(inspect.getsource(summary))
    coupables = []
    for noeud in ast.walk(arbre):
        if not (isinstance(noeud, ast.Call)
                and getattr(noeud.func, "id", None) in ("sorted", "min", "max")):
            continue
        noms = {n.attr for n in ast.walk(noeud) if isinstance(n, ast.Attribute)}
        noms |= {n.id for n in ast.walk(noeud) if isinstance(n, ast.Name)}
        if noms & {"review_candidates", "candidate", "candidats", "classees"}:
            coupables.append(f"L{noeud.lineno}")

    assert not coupables, f"le résumé classe des candidats : {coupables}"
    assert "rank_review" in inspect.getsource(summary)


def test_l_ordre_affiche_est_exactement_celui_du_classement():
    """Preuve par le texte : les rencontres apparaissent dans l'ordre rendu par
    `rank_review`, sans exception."""
    from src.agents.quant.conversation.review_ranking import rank_review
    from src.agents.quant.conversation.summary import rencontre_lisible

    run = _run_revue()
    attendu = [rencontre_lisible(l.candidate)
               for l in rank_review(run.response.review_candidates)]
    texte = "\n".join(render_resume(run))

    positions = [texte.index(nom) for nom in attendu if nom in texte]

    assert len(positions) >= 1
    assert positions == sorted(positions), "l'affichage réordonne le classement"


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
    l'apparence de deux mesures indépendantes.

    Le libellé a changé : au lieu d'exposer une « borne basse » puis de la
    démentir, on n'annonce plus qu'un seul chiffre et on dit ce qui manque.
    L'exigence est la même — ne jamais faire croire qu'une borne prudente
    existe — mais elle est portée par la phrase principale, pas par une note.
    """
    import dataclasses

    run = _run_revue()
    egales = tuple(
        dataclasses.replace(e, candidate=dataclasses.replace(
            e.candidate, probability_low=e.candidate.fair_probability))
        for e in run.response.review_candidates)
    run = dataclasses.replace(run, response=dataclasses.replace(
        run.response, review_candidates=egales))

    assert "intervalle prudent non encore estimé" in render(run)


def test_une_vraie_borne_basse_n_est_pas_signalee_a_tort():
    """Le jour où un intervalle sera estimé, la mise en garde doit disparaître
    d'elle-même — sinon elle deviendrait un mensonge inverse."""
    texte = render(_run_revue())
    assert "intervalle prudent non encore estimé" not in texte
    assert "borne basse mesurée" in texte


# ══ §15-C — Aucun événement exploitable : dire POURQUOI ═════════════════════
def _run_vide(refus=(), scannes=15, dans_fenetre=0):
    from src.agents.quant.conversation.observability import ScanTelemetry
    from src.agents.quant.conversation.recommend import run_recommendation

    contraintes = constraints_from_request(
        None, bankroll=Decimal("20"), sports=["basketball"],
        time_window=resolve_window("", _MAINTENANT))
    traces = _traces_refus(refus)

    def scan(window, sports, decision_time):
        return (_batch_vide(), ScanTelemetry(
            catalog_sports={2: "Basket"}, scanned_sports=("basketball",),
            catalog_events_total=scannes,
            events_outside_window=scannes - dans_fenetre,
            events_inside_window=dans_fenetre), traces)

    return run_recommendation(contraintes, now=_MAINTENANT, scan=scan,
                              persist_audit=None, capture=None, coverage=None)


def _traces_refus(refus):
    from datetime import timedelta

    from src.agents.quant.conversation.observability import EventTrace

    return tuple(
        EventTrace(bookmaker_event_id=f"x{i}", sport="basketball",
                   competition_label="—", kickoff=_MAINTENANT + timedelta(hours=1),
                   status=statut, reason=statut)
        for i, statut in enumerate(refus))


def _batch_vide():
    from tests.test_betting_conversation_safety import _batch
    return _batch()


def test_une_fenetre_sans_rencontre_le_dit_et_propose_d_elargir():
    """« Aucun modèle validé » serait FAUX ici : il n'y avait rien à évaluer.
    Dire la mauvaise raison envoie chercher au mauvais endroit."""
    texte = "\n".join(render_resume(_run_vide()))

    assert "Aucune rencontre dans cette fenêtre" in texte
    assert "15 événement(s) au catalogue" in texte
    assert "Élargis la période" in texte


def test_des_rencontres_non_evaluables_sont_ventilees_par_motif():
    texte = "\n".join(render_resume(_run_vide(
        refus=("EVENT_NOT_RESOLVED", "EVENT_NOT_RESOLVED", "INSUFFICIENT_FEATURES"),
        dans_fenetre=3)))

    assert "3 rencontre(s) dans la fenêtre, aucune évaluable" in texte
    assert "2 — rencontre non rattachée à une compétition connue" in texte
    assert "1 — historique trop mince pour ce match" in texte


def test_un_blocage_n_accuse_jamais_une_cause_non_verifiee():
    """`EVENT_NOT_RESOLVED` disait « participants inconnus de notre référentiel ».
    Sur le cas qui l'a révélé — PSG–Aston Villa — les DEUX participants étaient
    dans le référentiel : c'est la compétition européenne qui ne se rattachait à
    rien. Le libellé envoyait chercher au mauvais endroit."""
    texte = "\n".join(render_resume(_run_vide(
        refus=("EVENT_NOT_RESOLVED",), dans_fenetre=1)))

    assert "participants inconnus" not in texte
    assert "participants ou compétition non résolus" in texte


def test_un_blocage_structurel_ne_conseille_jamais_d_attendre():
    """« Re-scanne dans 24 h » sur une compétition non onboardée est un conseil
    qui ne peut pas marcher — le temps ne résout pas un référentiel."""
    texte = "\n".join(render_resume(_run_vide(
        refus=("COMPETITION_NOT_RESOLVED",), dans_fenetre=1)))

    assert "Attendre n'y changera rien" in texte
    assert "onboarder la compétition" in texte
    for interdit in ("re-scan", "réessay", "plus tard", "24 h"):
        assert interdit not in texte.lower()


def test_un_blocage_temporel_dit_que_le_temps_peut_aider():
    """L'inverse doit rester vrai : un historique trop mince s'enrichit."""
    texte = "\n".join(render_resume(_run_vide(
        refus=("INSUFFICIENT_FEATURES",), dans_fenetre=1)))

    assert "peuvent devenir évaluables" in texte
    assert "Attendre n'y changera rien" not in texte


def test_le_titre_garde_le_sport_demande_meme_sans_evenement():
    """Une fenêtre vide ne doit pas transformer « basket » en « tous sports » :
    le titre décrirait la recherche que l'utilisateur n'a pas faite."""
    texte = "\n".join(render_resume(_run_vide()))

    assert "Basket" in texte and "Tous sports" not in texte


# ══ §15-D — Panne provider : rien ne peut être affirmé ═════════════════════
def test_une_panne_de_scan_ne_laisse_rien_affirmer():
    """Le scan tombe : la chaîne rend un échec typé, sans preuve, et le garde
    bloque toute affirmation de pari qui prétendrait le contraire."""
    import json
    from unittest.mock import patch

    from src.agents.quant.betting_engine.bookmakers.winamax import connector as C
    from src.agents.quant.conversation import session
    from src.agents.quant.conversation import tools as T
    from src.agents.quant.conversation.evidence import EVIDENCE_KEY
    from src.agents.quant.conversation.guard import enforce

    def scan_casse(self, sport):
        raise ConnectionError("winamax.fr injoignable")

    session.reset()
    with patch.object(C.WinamaxConnector, "scan_catalog", scan_casse):
        charge = json.loads(T.betting_recommend.func(
            when="aujourd'hui", bankroll=20.0, sports=["tennis"],
            config={"configurable": {"thread_id": "panne"}}))

    assert charge["status"] in ("DATA_UNAVAILABLE", "TECHNICAL_FAILURE")
    assert charge[EVIDENCE_KEY] is None
    # Aucune cote, aucune sélection, aucun horaire dans le texte d'échec.
    for interdit in ("@", "cote ", "%", "€"):
        assert interdit not in charge["rendered"].lower(), interdit
    # Et le rendu d'échec lui-même passe : il explique, il n'affirme pas.
    assert not enforce(charge["rendered"], None).blocked


@pytest.mark.parametrize("invention", [
    "Mise 10 € sur Djokovic.",
    "Le meilleur pari du soir est Alcaraz.",
    "Djokovic est à 1.75 chez Winamax.",
    "Le moteur a retourné BET sur ce match.",
])
def test_aucune_invention_ne_passe_apres_une_panne(invention):
    from src.agents.quant.conversation.guard import enforce

    assert enforce(invention, None).blocked, invention
