"""Un fait vrai peut être hors sujet.

Le filtre d'extraction ne retenait qu'une condition : la phrase nomme un
participant. « Borges in run to Phoenix Challenger last week » la satisfait — vrai,
officiel, sur le bon joueur, et sans le moindre rapport avec son match de demain.
Affiché sous « contexte vérifié », il emprunte l'autorité de sa source pour un
contenu qui n'éclaire rien.

Ces tests verrouillent la frontière dans les deux sens : ce qui concerne
réellement la rencontre passe, le reste est écarté avec sa raison, et RIEN de
tout cela ne touche un calcul.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.enrichment.features import make
from src.agents.quant.enrichment.relevance import (
    NOT_EVENT_RELEVANT,
    RELEVANT,
    VALIDITE,
    evaluate,
    filter_relevant,
)

_KICKOFF = datetime(2026, 8, 9, 18, 30, tzinfo=timezone.utc)
_JOUEURS = ("Borges N.", "Darderi L.")


def _fait(type_, valeur, *, avant=timedelta(hours=6)):
    return make(type_, valeur, source="ATP", url="https://www.atptour.com/x",
                retrieved_at=_KICKOFF - avant)


def _verdict(type_, valeur, *, avant=timedelta(hours=6), competition="ATP tour"):
    return evaluate(_fait(type_, valeur, avant=avant), kickoff=_KICKOFF,
                    participants=_JOUEURS, competition_label=competition)


# ══ Le sujet ═══════════════════════════════════════════════════════════════
def test_un_fait_sur_un_autre_joueur_est_ecarte():
    verdict = _verdict("INJURY", "Sinner is dealing with a hip problem.")

    assert verdict.statut == NOT_EVENT_RELEVANT
    assert "participant" in verdict.raison


def test_un_fait_sur_un_participant_passe_le_premier_filtre():
    assert _verdict("INJURY", "Borges withdrew citing a right ankle injury.").retenu


# ══ La formulation : passé et résultats ════════════════════════════════════
@pytest.mark.parametrize("phrase", [
    "36 Borges in run to Phoenix Challenger last week.",
    "Borges won the title back in 2024.",
    "Darderi défendait son titre la semaine dernière.",
])
def test_un_fait_explicitement_passe_est_ecarte(phrase):
    verdict = _verdict("INJURY", phrase)

    assert verdict.statut == NOT_EVENT_RELEVANT


@pytest.mark.parametrize("phrase", [
    "Borges reached the final of the Phoenix Challenger.",
    "Borges was beaten by Naomi Osaka in straight sets.",
    "Darderi defeated the top seed in three sets.",
    "Borges lost to the defending champion.",
])
def test_un_resultat_raconte_un_match_deja_joue(phrase):
    """Signal indépendant du calendrier : un résultat porte, par définition, sur
    un match déjà disputé. Aucune date n'est nécessaire pour le savoir."""
    verdict = _verdict("INJURY", phrase)

    assert verdict.statut == NOT_EVENT_RELEVANT
    assert "déjà joué" in verdict.raison


def test_un_tournoi_nomme_et_different_est_ecarte():
    """Au tennis, la compétition canonique est le CIRCUIT (« ATP tour ») et non
    le tournoi : on ne connaît jamais le nom de l'épreuve du jour. Une première
    version comparait les mots de la compétition et se DÉSACTIVAIT silencieusement
    dans ce cas — « atp » et « tour » étant des mots vides, la comparaison portait
    sur un ensemble vide et laissait tout passer."""
    verdict = _verdict("INJURY",
                       "Borges is doubtful with an injury for the Phoenix Challenger.")

    assert verdict.statut == NOT_EVENT_RELEVANT
    assert "autre tournoi" in verdict.raison


def test_le_tournoi_de_la_rencontre_ne_declenche_pas_le_filtre():
    verdict = _verdict("INJURY",
                       "Borges is doubtful with an injury for the Cincinnati Open.",
                       competition="Cincinnati Open")

    assert verdict.retenu


# ══ La datation : par TYPE de fait, jamais un seuil unique ═════════════════
def test_une_composition_vieille_de_deux_jours_ne_dit_rien_du_match_du_soir():
    verdict = _verdict("LINEUP", "Borges is expected to start the match today.",
                       avant=timedelta(days=2))

    assert verdict.statut == NOT_EVENT_RELEVANT
    assert "validité" in verdict.raison


def test_un_classement_de_deux_jours_reste_valable():
    """Un classement ATP est hebdomadaire : deux jours ne le périment pas."""
    assert _verdict("OFFICIAL_RANKING",
                    "Borges is currently ranked inside the top thirty players.",
                    avant=timedelta(days=2)).retenu


def test_un_classement_de_vingt_jours_ne_l_est_plus():
    assert not _verdict("OFFICIAL_RANKING",
                        "Borges is currently ranked inside the top thirty players.",
                        avant=timedelta(days=20)).retenu


def test_la_validite_depend_du_type_pas_d_un_reglage_global():
    """C'est ce qui rend la règle défendable : une composition vieillit en heures,
    une surface de court ne change pas."""
    assert VALIDITE["LINEUP"] < VALIDITE["INJURY"] < VALIDITE["SURFACE"]


def test_un_type_non_datable_est_ecarte():
    """Mieux vaut ne rien montrer que montrer sans savoir dater."""
    from src.agents.quant.enrichment import relevance

    fait = _fait("INJURY", "Borges is doubtful with an injury for the match.")
    hors_table = type(fait)(**{**fait.__dict__, "feature_type": "H2H"})
    validite = VALIDITE.pop("H2H", None)
    affirmation = relevance._AFFIRMATIONS.pop("H2H", None)
    try:
        verdict = evaluate(hors_table, kickoff=_KICKOFF, participants=_JOUEURS)
        assert verdict.statut == NOT_EVENT_RELEVANT
        assert "non datable" in verdict.raison
    finally:
        VALIDITE["H2H"] = validite
        relevance._AFFIRMATIONS["H2H"] = affirmation


def test_un_fait_posterieur_au_coup_d_envoi_est_ecarte():
    verdict = evaluate(_fait("INJURY", "Borges is doubtful for the match.",
                             avant=timedelta(hours=-2)),
                       kickoff=_KICKOFF, participants=_JOUEURS)

    assert verdict.statut == NOT_EVENT_RELEVANT


# ══ Le tri, et ce qu'il rend ═══════════════════════════════════════════════
def test_le_tri_separe_les_retenus_des_ecartes_avec_leur_raison():
    faits = [
        _fait("INJURY", "Borges withdrew citing a right ankle injury."),
        _fait("INJURY", "Borges reached the final of the Phoenix Challenger."),
        _fait("INJURY", "Sinner is dealing with a hip problem."),
    ]

    retenus, ecartes = filter_relevant(faits, kickoff=_KICKOFF,
                                       participants=_JOUEURS,
                                       competition_label="ATP tour")

    assert len(retenus) == 1 and len(ecartes) == 2
    assert all(raison for _, raison in ecartes)      # chaque écart est motivé


def test_un_fait_ecarte_n_est_pas_un_fait_faux():
    """La distinction doit rester lisible : `NOT_EVENT_RELEVANT` dit hors sujet,
    jamais faux."""
    verdict = _verdict("INJURY", "Borges reached the final of the Phoenix Challenger.")

    assert verdict.statut == NOT_EVENT_RELEVANT
    assert "faux" not in verdict.raison.lower()


# ══ Internet reste informatif — rien ne change dans les calculs ════════════
def test_la_pertinence_ne_touche_aucun_calcul():
    """Preuve structurelle : le module ne connaît ni probabilité, ni EV, ni mise."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent / "src" / "agents"
              / "quant" / "enrichment" / "relevance.py")
    noms = {n.id for n in ast.walk(ast.parse(source.read_text()))
            if isinstance(n, ast.Name)}
    noms |= {n.attr for n in ast.walk(ast.parse(source.read_text()))
             if isinstance(n, ast.Attribute)}

    interdits = {"fair_probability", "probability_low", "expected_value_low",
                 "expected_value_mean", "edge_low", "edge_mean", "stake",
                 "kelly", "bookmaker_odds", "ranking_score"}

    assert not (noms & interdits), sorted(noms & interdits)


def test_le_filtre_ne_reordonne_pas_les_faits_retenus():
    """Il retire, il ne classe pas : l'ordre d'autorité reste celui de la source."""
    faits = [_fait("INJURY", "Borges withdrew citing a right ankle injury."),
             _fait("WITHDRAWAL", "Darderi has withdrawn from the tournament.")]

    retenus, _ = filter_relevant(faits, kickoff=_KICKOFF, participants=_JOUEURS)

    assert [f.value for f in retenus] == [f.value for f in faits]


# ══ La charge de la preuve : un fait doit AFFIRMER ce que son type promet ═══
# Énumérer ce qu'il faut rejeter est sans fin : après « last week » viennent les
# citations de presse, les palmarès, les notes de match d'un autre tournoi.
# Énumérer ce qu'il faut AFFIRMER est borné — et c'est au texte affiché sous
# « contexte vérifié » de porter la charge de la preuve.
@pytest.mark.parametrize("type_,phrase", [
    ("INJURY", "Musetti's 5-set victories against Darderi were the first here."),
    ("INJURY", "NOTE: Darderi aims to record his first ATP Tour win on home soil."),
    ("INJURY", '"Against Diego it is never going to be easy," Borges said.'),
    ("OFFICIAL_RANKING", "Borges trained in Brisbane ahead of the tournament."),
    ("LINEUP", "Darderi enjoys playing on this surface."),
    ("WEATHER", "Borges spoke to the press after practice."),
])
def test_une_phrase_qui_n_affirme_pas_son_type_est_ecartee(type_, phrase):
    verdict = _verdict(type_, phrase)

    assert verdict.statut == NOT_EVENT_RELEVANT
    assert "n'affirme rien" in verdict.raison


@pytest.mark.parametrize("type_,phrase", [
    ("INJURY", "Darderi is doubtful with a shoulder injury."),
    ("WITHDRAWAL", "Borges has withdrawn from the tournament."),
    ("OFFICIAL_RANKING", "Darderi is ranked inside the top thirty."),
    ("SURFACE", "Borges plays Darderi on an outdoor hard court."),
    ("LINEUP", "Borges is expected to start against Darderi."),
])
def test_une_phrase_qui_affirme_son_type_est_retenue(type_, phrase):
    assert _verdict(type_, phrase).retenu, phrase


def test_chaque_type_de_fait_declare_ce_qu_il_doit_affirmer():
    """Un type sans affirmation attendue laisserait repasser n'importe quoi sous
    son étiquette."""
    from src.agents.quant.enrichment.features import FEATURE_TYPES
    from src.agents.quant.enrichment.relevance import _AFFIRMATIONS

    manquants = FEATURE_TYPES - set(_AFFIRMATIONS)

    assert not manquants, f"types sans affirmation déclarée : {sorted(manquants)}"


# ══ §5 — Internet reste informatif : rien ne bouge dans la décision ════════
def test_le_filtre_de_pertinence_ne_deplace_aucun_chiffre():
    """La preuve demandée : mêmes entrées, mêmes probabilités, mêmes EV, mêmes
    mises — que la pertinence retienne un fait ou les écarte tous."""
    from decimal import Decimal

    from src.agents.quant.conversation.constraints import constraints_from_request
    from src.agents.quant.conversation.review_ranking import rank_review
    from src.agents.quant.conversation.window import PARIS, resolve_window
    from tests.test_betting_conversation_safety import _evaluation, _run

    maintenant = datetime(2026, 8, 6, 15, 30, tzinfo=PARIS)
    contraintes = constraints_from_request(
        None, bankroll=Decimal("20"), time_window=resolve_window("", maintenant))
    evaluations = [_evaluation(freshness=None), _evaluation(event="e2", freshness=None)]

    pertinent = make("INJURY", "Borges is doubtful with a shoulder injury.",
                     source="ATP", url="https://www.atptour.com/x", confidence="OFFICIAL")
    hors_sujet = make("INJURY", "Borges reached the final of the Phoenix Challenger.",
                      source="ATP", url="https://www.atptour.com/x", confidence="OFFICIAL")

    sans, _ = _run(contraintes, evaluations)
    avec_utile, _ = _run(contraintes, evaluations,
                         enrich=lambda *_a, **_k: {"e1": (pertinent,)})
    avec_bruit, _ = _run(contraintes, evaluations,
                         enrich=lambda *_a, **_k: {"e1": (hors_sujet,)})

    def chiffres(run):
        return [(e.candidate.candidate_id, str(e.candidate.fair_probability),
                 str(e.candidate.probability_low), str(e.candidate.expected_value_low),
                 str(e.candidate.edge_low), str(e.candidate.bookmaker_odds),
                 e.status.value, tuple(e.policy_reasons))
                for e in run.response.review_candidates]

    def ordre(run):
        return [l.candidate.candidate_id for l in rank_review(run.response.review_candidates)]

    assert chiffres(sans) == chiffres(avec_utile) == chiffres(avec_bruit)
    assert ordre(sans) == ordre(avec_utile) == ordre(avec_bruit)
    assert [str(p.total_stake) for p in sans.response.portfolios] == \
           [str(p.total_stake) for p in avec_bruit.response.portfolios]
