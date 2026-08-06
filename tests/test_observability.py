"""Observabilité — les nombres doivent se raccorder, et les absences se voir.

Le run rendait « 757 scannés · 99 dans la fenêtre · 60 évalués ». Trois nombres
exacts et impossibles à réconcilier : 60 comptait des SÉLECTIONS (deux ou trois
par match), et l'écart de 39 se justifiait par « par exemple hors fenêtre ou
données insuffisantes » — une phrase qui recompte hors fenêtre des événements
déjà comptés dedans, et qui ne peut donc jamais être fausse.

Ces tests vérifient trois choses distinctes :

  1. les compteurs s'additionnent exactement ;
  2. les niveaux de couverture ne se confondent pas ;
  3. cette wave n'a changé AUCUNE décision métier.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.agents.quant.conversation.constraints import constraints_from_request
from src.agents.quant.conversation.observability import (
    NON_MESURE,
    EventTrace,
    ModelReadiness,
    RunObservability,
    ScanTelemetry,
    build_traces,
    primary_blocker,
)
from src.agents.quant.conversation.recommend import COMPLETED, run_recommendation
from src.agents.quant.conversation.renderer import GATE_SEQUENCE, render
from src.agents.quant.conversation.window import PARIS, resolve_window

from tests.test_betting_conversation_safety import _evaluation, _run

_MAINTENANT = datetime(2026, 8, 6, 15, 30, tzinfo=PARIS)


def _contraintes(**kw):
    return constraints_from_request(
        None, bankroll=Decimal("20"),
        time_window=resolve_window("", _MAINTENANT), **kw)


# ══ §4 — Chaîne de compteurs cohérente ═══════════════════════════════════════
def test_les_compteurs_s_additionnent_exactement():
    """L'identité vérifiable : dans la fenêtre = refus avant évaluation + évalués.
    Sans elle, tout écart se justifie par une phrase que rien ne peut réfuter."""
    run, _ = _run(_contraintes(), [_evaluation(), _evaluation(event="e2")],
                  refus=[("football", "EVENT_NOT_RESOLVED"),
                         ("hockey", "DATA_TOO_STALE"),
                         ("football", "EVENT_NOT_RESOLVED")],
                  scannes=100)
    obs = run.observability

    coherent, detail = obs.counters_balance()

    assert coherent, detail
    assert obs.counters["events_inside_window"] == 5
    assert obs.counters["events_evaluated"] == 2
    assert sum(obs.pre_evaluation_refusals.values()) == 3


def test_evenements_et_selections_sont_deux_compteurs_distincts():
    """« 60 évalués » comptait des sélections. Deux définitions sous un seul nom :
    aucun des deux ne pouvait se raccorder au reste."""
    run, _ = _run(_contraintes(),
                  [_evaluation(selection=s) for s in ("player_a", "player_b")])
    obs = run.observability

    assert obs.events_evaluated == 1          # une rencontre
    assert obs.selections_evaluated == 2      # deux sélections
    assert run.evidence.events_evaluated == 1


def test_hors_fenetre_et_dans_la_fenetre_ne_se_recoupent_pas():
    run, _ = _run(_contraintes(), [_evaluation()], scannes=100)
    c = run.observability.counters

    assert c["events_outside_window"] + c["events_inside_window"] == c["catalog_events_total"]


def test_une_incoherence_de_compteurs_est_signalee_pas_masquee():
    """Le contrôle doit pouvoir échouer, sinon il ne prouve rien."""
    obs = RunObservability(
        telemetry=ScanTelemetry(events_inside_window=10),
        traces=(EventTrace("e1", "tennis", "ATP", _MAINTENANT, "EVALUATED", "ok",
                           selections=2),),
        model_capable_sports=("tennis",))

    coherent, detail = obs.counters_balance()

    assert not coherent and "incohérence" in detail


# ══ §2 — Les niveaux de couverture ne se confondent pas ══════════════════════
def test_catalogue_et_model_capable_sont_deux_nombres_distincts():
    """« 7 sports scannés » était vrai et trompeur : Winamax en expose 29. Le même
    nombre décrivait ce que le bookmaker propose et ce qu'on sait modéliser."""
    run, _ = _run(_contraintes(), [_evaluation()])
    rendu = render(run)

    assert "Sports exposés par Winamax : **3**" in rendu       # catalogue du harnais
    assert "Sports disposant d'un modèle : **7**" in rendu     # SPORT_MODULES réel
    assert "Sports ayant atteint l'évaluation : **1**" in rendu


def test_les_sports_en_fenetre_ne_sont_pas_les_sports_evalues():
    run, _ = _run(_contraintes(), [_evaluation()],
                  refus=[("hockey", "DATA_TOO_STALE")])
    obs = run.observability

    assert obs.sports_in_window == ("hockey", "tennis")
    assert obs.sports_evaluated == ("tennis",)


def test_un_catalogue_indisponible_ne_devient_pas_zero():
    """Le catalogue de sports vient d'un appel réseau qui peut échouer. Écrire
    « 0 sport exposé » transformerait une panne en mesure."""
    obs = RunObservability(telemetry=ScanTelemetry(), traces=(),
                           model_capable_sports=("tennis",))
    run, _ = _run(_contraintes(), [_evaluation()])
    rendu = render(
        type(run)(run.status, run.constraints, run.response, run.evidence,
                  observability=obs))

    assert "Sports exposés par Winamax : **INDISPONIBLE**" in rendu


# ══ §5, §7 — Candidats de revue et premier bloqueur ══════════════════════════
def test_review_candidates_sont_rendus_avec_leurs_raisons():
    """Deux raisons distinctes s'accumulent : la maturité du modèle et une
    fraîcheur non mesurable. Les fondre sous « EXPERIMENTAL » perdrait la
    seconde, qui se répare ailleurs."""
    run, _ = _run(_contraintes(),
                  [_evaluation(maturity="EXPERIMENTAL", freshness=None)])
    rendu = render(run)

    assert run.response.outcome.value == "REVIEW_CANDIDATES"
    assert "Candidats à examiner — NON MISABLES" in rendu
    assert "premier bloqueur : **EXPERIMENTAL_REVIEW_ONLY**" in rendu
    assert "Raisons complètes : EXPERIMENTAL_REVIEW_ONLY, FRESHNESS_UNKNOWN" in rendu


def test_le_premier_bloqueur_vient_de_l_ordre_du_domaine():
    """`evaluate_eligibility` court-circuite au premier rejet dur et accumule ses
    raisons de revue dans l'ordre de ses portes. `policy_reasons[0]` EST donc le
    premier bloqueur — le renderer n'a aucun ordre à inventer."""
    class _Eval:
        policy_reasons = ("EXPERIMENTAL_REVIEW_ONLY", "FRESHNESS_UNKNOWN")

    assert primary_blocker(_Eval()) == "EXPERIMENTAL_REVIEW_ONLY"


def test_aucune_mise_ni_instruction_de_placement_en_revue():
    run, _ = _run(_contraintes(), [_evaluation()])
    rendu = render(run)

    assert "Aucune mise recommandée" in rendu
    for interdit in ("meilleur pari", "proche de passer", "presque recommandé",
                     "ouvrez winamax", "placez", "mise recommandée de"):
        assert interdit.lower() not in rendu.lower()
    assert "Cette sélection n'est pas une recommandation de pari." in rendu


def test_chaque_candidat_porte_sa_provenance():
    """§14 : sans event_id, market_id et instant d'observation, une ligne
    affichée n'est rattachable à aucun scan."""
    run, _ = _run(_contraintes(), [_evaluation()])
    rendu = render(run)

    assert "Provenance : `e1`" in rendu
    assert "winamax:e1:MATCH_WINNER" in rendu


# ══ §5 — Une absence n'est jamais un zéro ════════════════════════════════════
def test_une_freshness_non_mesuree_s_affiche_non_mesuree():
    run, _ = _run(_contraintes(), [_evaluation(freshness=None)])
    rendu = render(run)

    assert f"fraîcheur : {NON_MESURE}" in rendu
    assert "fraîcheur : 0.00 %" not in rendu


def test_une_fiabilite_absente_ne_devient_pas_zero():
    """`calibration_score=None` signifie que la calibration n'a pas été mesurée,
    pas qu'elle vaut zéro — ce qui serait le pire score possible."""
    run, _ = _run(_contraintes(), [_evaluation()])
    rendu = render(run)

    assert f"fiabilité modèle : {NON_MESURE}" in rendu


# ══ §13 — Aucun candidat hors fenêtre ════════════════════════════════════════
def test_un_candidat_hors_fenetre_n_est_jamais_rendu_comme_candidat():
    """La fenêtre filtre déjà au scan. Ce garde ferme le cas où un candidat
    proviendrait d'ailleurs — il ne remplace pas le filtre, il le double."""
    contraintes = constraints_from_request(
        None, bankroll=Decimal("20"),
        time_window=resolve_window("ce soir", _MAINTENANT))
    loin = _evaluation()
    objet = type(loin)
    hors = objet(**{**loin.__dict__,
                    "scheduled_at": _MAINTENANT + timedelta(days=5)})

    run, _ = _run(contraintes, [hors])
    rendu = render(run)

    assert "coup d'envoi hors fenêtre" in rendu
    assert "Cote bookmaker" not in rendu


# ══ §8 — Matrice des bloqueurs, par couche ═══════════════════════════════════
def test_la_matrice_distingue_les_couches():
    """Un `MODEL_NOT_SUPPORTED` de l'Advisor et un `SPORT_NOT_SUPPORTED` du
    moteur se réparent à des endroits différents ; les additionner produit un
    nombre qui ne désigne aucune action."""
    run, _ = _run(_contraintes(), [_evaluation()],
                  refus=[("football", "EVENT_NOT_RESOLVED"),
                         ("hockey", "DATA_TOO_STALE")])
    matrice = run.observability.blocker_matrix()

    assert matrice["refus avant modèle (Betting Engine)"] == {
        "DATA_TOO_STALE": 1, "EVENT_NOT_RESOLVED": 1}
    assert matrice["statut Advisor"]["REVIEW_ONLY"] == 1
    assert "EXPERIMENTAL_REVIEW_ONLY" in matrice["raisons Advisor"]
    assert "autres" not in matrice


# ══ §9 — Readiness : maturité d'un MODÈLE ════════════════════════════════════
def test_la_readiness_ne_se_traduit_jamais_en_proximite_de_pari():
    readiness = (ModelReadiness(
        model_name="tennis_elo", model_version="tennis.elo.v0", sport="tennis",
        status="EXPERIMENTAL", passed=("a", "b", "c", "d", "e", "f"),
        failed=("min_data_coverage",),
        not_measurable=("positive_clv",), monitoring=(("spread", "PASS"),),
        blockers=("min_data_coverage", "positive_clv")),)

    run, _ = _run(_contraintes(), [_evaluation()], readiness=lambda _: readiness)
    rendu = render(run)

    assert "Critères requis satisfaits : 6/8" in rendu
    assert "Bloqueurs vers SUPPORTED : min_data_coverage, positive_clv" in rendu
    assert "presque validé" not in rendu.lower()
    assert "MATURITÉ D'UN MODÈLE" in rendu


def test_la_readiness_reste_hors_du_rendu_normal():
    """Elle rejoue une validation walk-forward : c'est une mesure du modèle, pas
    du run, et elle ne doit rien coûter à une réponse ordinaire."""
    run, _ = _run(_contraintes(), [_evaluation()])

    assert run.observability.readiness == ()


# ══ §10, §12 — Mode debug ════════════════════════════════════════════════════
def test_le_mode_normal_ne_deverse_pas_le_catalogue():
    run, _ = _run(_contraintes(), [_evaluation(event=f"e{i}") for i in range(12)])
    normal, complet = render(run), render(run, debug=True)

    assert "Chemin de décision par événement" not in normal
    assert "Chemin de décision par événement" in complet
    assert "Catalogue découvert dans ce run" in complet
    assert len(complet) > len(normal)


def test_le_debug_porte_la_portee_du_state():
    """§19 : la portée est une information d'exploitation, pas une promesse."""
    run, _ = _run(_contraintes(), [_evaluation()])

    assert "constraints_state_scope    process/thread" in render(run, debug=True)


def test_le_chemin_de_decision_vient_du_statut_typé_du_domaine():
    run, _ = _run(_contraintes(), [_evaluation()],
                  refus=[("hockey", "DATA_TOO_STALE")])
    rendu = render(run, debug=True)

    assert "[DATA_TOO_STALE" in rendu and "[EVALUATED" in rendu


def test_l_ordre_des_portes_declare_couvre_les_statuts_reels():
    """Un ordre recopié à la main diverge. Celui-ci est confronté aux statuts que
    le domaine sait réellement produire."""
    from src.agents.quant.betting_engine.live_evaluation import LiveEvaluationStatus

    declare = " ".join(GATE_SEQUENCE).lower()
    correspondances = {
        LiveEvaluationStatus.SPORT_NOT_SUPPORTED: "sport dispatch",
        LiveEvaluationStatus.EVENT_NOT_RESOLVED: "participant identity",
        LiveEvaluationStatus.COMPETITION_NOT_RESOLVED: "competition identity",
        LiveEvaluationStatus.MARKET_CANONICALIZATION_FAILED: "market canonicalization",
        LiveEvaluationStatus.COMPETITION_NOT_COVERED: "provider coverage",
        LiveEvaluationStatus.INSUFFICIENT_FEATURES: "feature readiness",
        LiveEvaluationStatus.DATA_TOO_STALE: "freshness",
        LiveEvaluationStatus.EVALUATED: "model evaluation",
    }
    for statut, porte in correspondances.items():
        assert porte in declare, f"{statut.value} sans porte déclarée"


def test_build_traces_conserve_le_sport_de_chaque_refus():
    """`SkippedEvaluation` réduit un refus à des identifiants : aucun refus n'y
    est attribuable à un sport. C'est pourquoi la trace part du batch de
    domaine, où chaque résultat est encore accompagné de son événement brut."""
    class _Raw:
        bookmaker_event_id, sport, competition = "b1", "hockey", "NHL"
        start_time = _MAINTENANT

    class _Statut:
        value = "DATA_TOO_STALE"

    class _Res:
        status, reason = _Statut(), "trop ancien"
        canonical_event, predictions, freshness_score = None, {}, None

    traces = build_traces([(_Raw(), _Res())])

    assert traces[0].sport == "hockey" and traces[0].competition_label == "NHL"
    assert not traces[0].evaluated


# ══ §16 — Invariance métier stricte ══════════════════════════════════════════
def _decision_snapshot(response) -> dict:
    """Tout ce qui décide de l'argent, et rien d'autre."""
    return {
        "outcome": response.outcome.value,
        "portfolios": [
            {
                "total_stake": str(pf.total_stake),
                "unallocated": str(pf.unallocated_bankroll),
                "lines": [
                    {"stake": str(l.stake), "total_odds": str(l.total_odds),
                     "ev": str(l.expected_value), "worst": str(l.worst_case_ev),
                     "prob": str(l.estimated_probability),
                     "legs": [(g.selection, str(g.odds)) for g in l.legs]}
                    for l in pf.lines
                ],
            }
            for pf in response.portfolios
        ],
        "review": [
            (e.candidate.event_id, e.candidate.selection, e.status.value,
             str(e.candidate.fair_probability), str(e.candidate.expected_value_mean),
             str(e.candidate.expected_value_low), tuple(e.policy_reasons))
            for e in response.review_candidates
        ],
        "rejections": dict(response.rejection_summary),
        "warnings": list(response.warnings),
    }


#: Golden figé AVANT la wave observabilité, sur le même jeu d'entrée.
_GOLDEN = {
    "outcome": "REVIEW_CANDIDATES",
    "portfolios": [],
    "review": [
        ("e1", "player_a", "REVIEW_ONLY", "0.57", "0.1970", "0.1550",
         ("EXPERIMENTAL_REVIEW_ONLY", "FRESHNESS_UNKNOWN")),
    ],
    "rejections": {},
    "warnings": [],
}


def test_aucune_decision_metier_n_a_change():
    """La preuve que cette wave est purement additive : mêmes entrées, même
    `RecommendationResponse`. Probabilités, EV, statuts, mises et motifs sont
    comparés champ à champ — pas seulement l'issue."""
    run, _ = _run(_contraintes(), [_evaluation(freshness=None)])

    assert run.status == COMPLETED
    assert _decision_snapshot(run.response) == _GOLDEN


def test_l_observabilite_est_detachable():
    """Le vrai critère d'additivité : retirer l'observabilité ne change aucune
    décision. Si un jour elle en changeait une, ce test tomberait."""
    avec, _ = _run(_contraintes(), [_evaluation(freshness=None)])
    sans, _ = _run(_contraintes(), [_evaluation(freshness=None)])
    objet = type(sans)
    ampute = objet(sans.status, sans.constraints, sans.response, sans.evidence,
                   observability=None)

    assert _decision_snapshot(avec.response) == _decision_snapshot(ampute.response)
    assert render(ampute)          # le rendu dégradé reste possible, sans planter
