"""Fraîcheur multi-marché — à la granularité que la source fournit, pas plus fine.

Le point mesuré, et il commande tout le reste : Winamax ne date RIEN. Ni l'état,
ni le match, ni le marché, ni la cote — `odds[id]` est un flottant nu. Le seul
instant honnête est celui de notre récupération, partagé par tous les marchés
d'un même appel.

Ces tests verrouillent trois refus : ne pas inventer une granularité plus fine,
ne pas confondre « je ne sais pas » avec « c'est périmé », et ne jamais laisser
une capacité s'auto-délivrer le critère.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.markets.freshness import (
    AGE_MAX,
    GRANULARITE_EFFECTIVE_WINAMAX,
    GRANULARITE_SOURCE_WINAMAX,
    FreshnessGranularity,
    FreshnessStatus,
    evaluer,
    partagee_par_evenement,
)

T = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def test_la_granularite_declaree_est_celle_qui_a_ete_mesuree():
    """La source ne date rien ; notre récupération, si. La granularité EFFECTIVE
    est donc le snapshot — et surtout pas la sélection."""
    assert GRANULARITE_SOURCE_WINAMAX is FreshnessGranularity.NONE
    assert GRANULARITE_EFFECTIVE_WINAMAX is FreshnessGranularity.SNAPSHOT
    assert GRANULARITE_EFFECTIVE_WINAMAX is not FreshnessGranularity.SELECTION


def test_une_observation_recente_est_mesurable():
    f = evaluer(T - timedelta(seconds=30), T)
    assert f.status is FreshnessStatus.MEASURABLE and f.measurable
    assert f.age_seconds == 30
    assert 0.9 < f.score < 1.0
    assert f.granularity is FreshnessGranularity.SNAPSHOT


def test_sans_instant_d_observation_c_est_inconnu_et_non_zero():
    """Un score absent n'est pas 0 : zéro serait une mesure, et la pire —
    « parfaitement périmé »."""
    for observed, decision in ((None, T), (T, None), (None, None)):
        f = evaluer(observed, decision)
        assert f.status is FreshnessStatus.UNKNOWN
        assert f.score is None
        assert not f.measurable


def test_inconnu_et_perime_ne_se_confondent_pas():
    """L'un dit « je ne sais pas », l'autre « je sais, et c'est vieux ». Deux
    rapports différents, deux réparations différentes."""
    inconnu = evaluer(None, T)
    perime = evaluer(T - AGE_MAX - timedelta(minutes=1), T)
    assert inconnu.status is FreshnessStatus.UNKNOWN and inconnu.score is None
    assert perime.status is FreshnessStatus.STALE and perime.score == 0.0
    assert inconnu.status != perime.status


def test_une_observation_posterieure_a_la_decision_n_est_pas_tres_fraiche():
    """Une cote datée APRÈS la décision est une incohérence d'horodatage. La
    traiter comme très fraîche récompenserait le bug."""
    f = evaluer(T + timedelta(minutes=5), T)
    assert f.status is FreshnessStatus.UNKNOWN
    assert f.score is None
    assert "postérieure" in f.reason


def test_le_score_decroit_avec_l_age():
    ages = [timedelta(seconds=0), timedelta(minutes=5), timedelta(minutes=10)]
    scores = [evaluer(T - a, T).score for a in ages]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 1.0


def test_un_snapshot_unique_se_partage():
    """Une page Winamax livre tous les marchés d'un événement en une réponse :
    la fraîcheur se mesure une fois. On ne moyenne jamais des instants."""
    class _Obs:
        def __init__(self, quand): self.observed_at = quand

    assert partagee_par_evenement([_Obs(T), _Obs(T), _Obs(T)])
    assert not partagee_par_evenement([_Obs(T), _Obs(T - timedelta(minutes=1))])
    assert not partagee_par_evenement([_Obs(T), _Obs(None)])


# ── Le pricing porte la mesure, il ne la fabrique pas ────────────────────────

def test_le_pricing_attache_la_fraicheur_mesuree():
    from src.agents.quant.betting_engine.markets.families import MarketFamily
    from src.agents.quant.betting_engine.markets.pricing import (
        MarketPricing, PricingStatus, avec_fraicheur,
    )

    prix = MarketPricing(event_id="e", sport="football", family=MarketFamily.TOTALS,
                         status=PricingStatus.PRICED)
    assert prix.freshness is None and prix.freshness_detail is None

    date = avec_fraicheur(prix, T - timedelta(seconds=60), T)
    assert date.freshness is not None
    assert date.freshness_detail.status is FreshnessStatus.MEASURABLE
    assert date.freshness_detail.observed_at == T - timedelta(seconds=60)

    sans = avec_fraicheur(prix, None, T)
    assert sans.freshness is None
    assert sans.freshness_detail.status is FreshnessStatus.UNKNOWN


def test_aucune_capacite_ne_s_auto_declare_mesurable():
    """Le critère de maturité ne doit jamais tenir à une constante écrite dans un
    module de marché — c'est ce que le garde existant interdit, et il doit valoir
    pour le nouveau chemin multi-marché aussi."""
    import pathlib

    racine = pathlib.Path(__file__).resolve().parent.parent / "src" / "agents" / "quant"
    for fichier in (racine / "betting_engine" / "markets").rglob("*.py"):
        source = fichier.read_text(encoding="utf-8")
        assert "FRESHNESS_MEASURABLE" not in source, fichier.name
