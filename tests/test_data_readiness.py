"""Fraîcheur et couverture — mesurées pour de vrai, ou déclarées non mesurables.

Le rapport de la vague précédente annonçait « FRESHNESS_UNKNOWN généralisé ». La
mesure a montré autre chose : deux causes distinctes produisaient le même
symptôme, et une troisième affirmation du rapport était simplement fausse.

  1. `gateway.data_freshness` codait `sport="football"` en dur. Pour une
     compétition de baseball, elle allait chercher des données de football,
     obtenait NoDataAvailableError et rendait `None` — la fraîcheur devenait
     « inconnue » pour un motif faux.

  2. Un `degraded=True` était traité comme une absence de mesure. Or il dit que
     la BASE est plus faible (`fetched_at` au lieu de `published_time`), pas que
     la mesure manque. Les confondre transformait une fraîcheur mesurée à 0,0001
     — donc une donnée manifestement périmée — en « inconnue », c'est-à-dire en
     un doute plus favorable que la mesure elle-même.

Ces tests portent sur le CONTRAT, pas sur un sport : c'est ce qui les rend
valides pour les schémas 2-way comme 3-way.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
)

#: MÊME instant que le harnais live réutilisé plus bas : une date locale
#: décalerait toutes les fraîcheurs relatives sans que le test ne le dise.
from tests.test_live_evaluation import _DECISION  # noqa: E402


# ══ §2 — Le sport vient de l'identifiant, jamais d'un défaut ═════════════════
@pytest.mark.parametrize("competition,sport", [
    ("competition:football:fra:ligue1", "football"),
    ("competition:baseball:usa:mlb", "baseball"),
    ("competition:tennis:atp:tour", "tennis"),
    ("competition:hockey:usa:nhl", "hockey"),
])
def test_le_sport_est_lu_sur_l_identifiant_de_competition(competition, sport):
    from src.agents.quant.gateway.gateway import _sport_of

    assert _sport_of(competition) == sport


@pytest.mark.parametrize("identifiant", ["", "bidon", "team:football:psg", "competition"])
def test_un_identifiant_non_canonique_ne_donne_aucun_sport(identifiant):
    """On ne devine pas un sport : un identifiant hors forme rend `None`, et la
    fraîcheur sera honnêtement non mesurable."""
    from src.agents.quant.gateway.gateway import _sport_of

    assert _sport_of(identifiant) is None


def test_un_sport_non_couvert_par_la_gateway_rend_none_sans_lever():
    """Les six sports non-football n'ont aucun module Gateway. Le dire par `None`
    est correct ; aller chercher des données de FOOTBALL pour eux ne l'était
    pas."""
    from src.agents.quant.gateway import gateway

    assert gateway.data_freshness("competition:baseball:usa:mlb", "2026") is None


# ══ §3 — degraded ≠ non mesurable ════════════════════════════════════════════
def _resultat(freshness):
    """Le harnais live existant, avec la fraîcheur qu'on veut éprouver. On
    réutilise sa Gateway complète : construire la nôtre reviendrait à réimplémenter
    `recent_form` et `standings_strength` pour tester la fraîcheur."""
    from tests.test_live_evaluation import _FreshGateway, _run

    return _run(_FreshGateway(freshness))


def _mesure(score, effective, *, degraded):
    from src.agents.quant.gateway.gateway import DataFreshness

    return DataFreshness(
        freshness_score=score, effective_time=effective,
        basis="fetched_at" if degraded else "published_time",
        degraded=degraded, stale=False)


def test_une_mesure_degradee_est_propagee_et_signalee():
    """Le cœur du correctif : la base est faible, la mesure existe. On propage le
    score ET on signale la dégradation — l'un sans l'autre ment dans un sens ou
    dans l'autre."""
    from src.agents.quant.betting_engine.live_evaluation import _FRESHNESS_DEGRADED

    res = _resultat(_mesure(0.42, _DECISION - timedelta(hours=1), degraded=True))

    assert res.status is S.EVALUATED
    assert res.freshness_score == 0.42
    assert _FRESHNESS_DEGRADED in res.warnings


def test_une_mesure_fiable_est_propagee_sans_avertissement():
    from src.agents.quant.betting_engine.live_evaluation import _FRESHNESS_DEGRADED

    res = _resultat(_mesure(0.95, _DECISION - timedelta(minutes=5), degraded=False))

    assert res.freshness_score == 0.95
    assert _FRESHNESS_DEGRADED not in res.warnings


def test_une_absence_de_donnee_reste_non_mesurable():
    """`None` veut dire qu'aucun horodatage n'est exploitable. Le contrat interdit
    d'en faire un zéro comme d'en faire une fraîcheur."""
    assert _resultat(None).freshness_score is None


def test_un_horodatage_absent_reste_non_mesurable():
    assert _resultat(_mesure(0.9, None, degraded=False)).freshness_score is None


def test_une_donnee_trop_ancienne_est_refusee_meme_avec_base_degradee():
    """Une base faible ne dispense pas du contrôle d'ancienneté — c'est même le
    cas où il sert le plus."""
    res = _resultat(_mesure(0.0001, _DECISION - timedelta(days=30), degraded=True))

    assert res.status is S.DATA_TOO_STALE


# ══ §16 — Aucun seuil de maturité modifié ════════════════════════════════════
def test_aucun_seuil_de_maturite_n_a_bouge():
    """La mission corrige des MESURES, jamais des barres. Un seuil déplacé ferait
    passer un modèle sans qu'aucune donnée n'ait changé."""
    from src.agents.quant.betting_engine.maturity import load_maturity_policy

    p = load_maturity_policy()

    assert p.criteria["min_data_coverage"] == 0.9
    assert p.criteria["min_data_quality"] == 0.8
    assert p.criteria["min_sample_size"] == 500
    assert p.criteria["min_temporal_folds"] == 3
    assert p.criteria["max_calibration_error"] == 0.05
    assert p.criteria["min_clv_events"] == 30


def test_les_criteres_requis_restent_les_memes():
    from src.agents.quant.betting_engine.maturity import load_maturity_policy

    requis = {k for k, v in load_maturity_policy().required_for_support.items() if v}

    assert requis == {
        "max_calibration_error", "measurable_live_freshness", "min_data_coverage",
        "min_data_quality", "min_sample_size", "min_temporal_folds",
        "must_beat_baselines", "positive_clv",
    }


def test_la_maturite_reste_derivee_mecaniquement():
    """Aucun modèle ne devient SUPPORTED par cette wave : les statuts sont dérivés
    des critères, et les critères de données restent ceux qu'on mesure."""
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS

    statuts = {cle: _ASSESSORS[cle]().decision.status
               for cle in ("nhl", "atp", "fl1")}

    assert set(statuts.values()) == {"EXPERIMENTAL"}
