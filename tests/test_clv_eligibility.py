"""Quelles observations ont le droit de PROUVER une maturité.

45 décisions NHL ont été capturées 55 jours avant leur coup d'envoi, par les
captures manuelles antérieures au collecteur. Leur CLV, quand elle se formera,
mesurera deux mois de dérive de marché — pas l'avance d'une décision sur sa
clôture. Elles ne sont ni fausses ni à supprimer : elles sont hors du protocole
de collecte actuel, et une preuve doit porter sur un protocole unique.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.clv.collect import (
    FENETRE_CLOTURE,
    HORIZON_DECISION,
)
from src.agents.quant.betting_engine.clv.eligibility import (
    CLOSING_OUTSIDE_WINDOW,
    CLOSING_POST_KICKOFF,
    DECISION_TOO_LATE,
    ELIGIBLE,
    KICKOFF_UNREADABLE,
    LEGACY_DECISION_HORIZON,
    POLICY_VERSION,
    eligible,
    evaluate,
    exclusions,
    kickoff_de,
)
from src.agents.quant.betting_engine.clv.observation import (
    ObservationPhase,
    OddsObservation,
)

_KICKOFF = datetime(2026, 8, 8, 14, 30, 0, tzinfo=timezone.utc)
_EVENT = f"event:tennis:tour:{_KICKOFF:%Y-%m-%dT%H:%M:%S}Z:player_a=a|player_b=b"


def _obs(phase, *, avant, event_id=_EVENT):
    return OddsObservation(
        event_id=event_id, market_type="MATCH_WINNER", selection="player_a",
        bookmaker="winamax", decimal_odds=Decimal("2.0"),
        observed_at=_KICKOFF - avant, phase=phase, source="synthetic",
        source_event_id="x", run_id=None)


# ══ Le coup d'envoi se lit par MOTIF, jamais par découpage ═════════════════
def test_l_horodatage_est_extrait_sans_couper_sur_les_deux_points():
    """`event:tennis:tour:2026-08-08T14:30:00Z:…` découpé sur « : » rend
    « 2026-08-08T14 » — une heure ronde plausible et fausse. L'erreur est
    silencieuse : elle décale les temps d'avance de dizaines de minutes et
    fabrique des clôtures « postérieures au coup d'envoi » qui n'existent pas."""
    assert kickoff_de(_EVENT) == _KICKOFF
    assert kickoff_de(_EVENT).minute == 30          # pas 0


def test_une_identite_sans_horodatage_est_inadmissible():
    verdict = evaluate(_obs(ObservationPhase.DECISION, avant=timedelta(hours=5),
                            event_id="event:tennis:tour:sans-date:a=1|b=2"))

    assert not verdict.admissible and verdict.raison == KICKOFF_UNREADABLE


# ══ La fenêtre est DÉRIVÉE de la policy du collecteur ══════════════════════
def test_la_fenetre_derive_de_la_policy_de_collecte():
    """Inventer un seuil propre à la preuve permettrait de le régler jusqu'à
    obtenir le résultat voulu. Le dériver interdit ce geste."""
    import inspect

    from src.agents.quant.betting_engine.clv import eligibility

    source = inspect.getsource(eligibility)

    assert "HORIZON_DECISION" in source and "FENETRE_CLOTURE" in source
    assert str(int(HORIZON_DECISION.total_seconds() // 3600)) in POLICY_VERSION


@pytest.mark.parametrize("avant,attendu", [
    (timedelta(hours=5), ELIGIBLE),
    (timedelta(hours=47), ELIGIBLE),
    (timedelta(minutes=31), ELIGIBLE),
    (timedelta(days=55), LEGACY_DECISION_HORIZON),      # le cas NHL
    (timedelta(hours=49), LEGACY_DECISION_HORIZON),
    (timedelta(minutes=20), DECISION_TOO_LATE),
])
def test_l_admissibilite_d_une_decision_suit_son_avance(avant, attendu):
    verdict = evaluate(_obs(ObservationPhase.DECISION, avant=avant))

    assert verdict.raison == attendu
    assert verdict.admissible == (attendu == ELIGIBLE)


@pytest.mark.parametrize("avant,attendu", [
    (timedelta(minutes=5), ELIGIBLE),
    (timedelta(minutes=29), ELIGIBLE),
    (timedelta(minutes=31), CLOSING_OUTSIDE_WINDOW),
    (timedelta(minutes=-5), CLOSING_POST_KICKOFF),
])
def test_l_admissibilite_d_une_cloture_suit_la_fenetre(avant, attendu):
    verdict = evaluate(_obs(ObservationPhase.CLOSING, avant=avant))

    assert verdict.raison == attendu


def test_une_decision_sous_la_fenetre_de_cloture_decrit_autre_chose():
    """Le collecteur actuel y écrirait une CLÔTURE : l'observation ne dit pas ce
    que son étiquette annonce."""
    verdict = evaluate(_obs(ObservationPhase.DECISION,
                            avant=FENETRE_CLOTURE - timedelta(minutes=1)))

    assert verdict.raison == DECISION_TOO_LATE


# ══ Rien n'est supprimé, seule l'admissibilité change ══════════════════════
def test_le_filtre_ne_touche_pas_l_historique():
    """Les observations restent immuables : le filtre RETIENT, il n'efface ni ne
    corrige."""
    lot = [_obs(ObservationPhase.DECISION, avant=timedelta(days=55)),
           _obs(ObservationPhase.DECISION, avant=timedelta(hours=5))]
    avant = list(lot)

    retenues = eligible(lot)

    assert lot == avant                    # la liste source est intacte
    assert len(retenues) == 1


def test_les_motifs_d_exclusion_sont_comptes_jamais_muets():
    lot = [_obs(ObservationPhase.DECISION, avant=timedelta(days=55))] * 3 + \
          [_obs(ObservationPhase.CLOSING, avant=timedelta(minutes=-5))]

    assert exclusions(lot) == {LEGACY_DECISION_HORIZON: 3, CLOSING_POST_KICKOFF: 1}


def test_une_exclusion_ne_peut_qu_enlever_jamais_ajouter():
    """Garantie de sens : le filtre ne peut pas gonfler l'échantillon, donc il ne
    peut pas rendre un critère plus facile à franchir."""
    lot = [_obs(ObservationPhase.DECISION, avant=timedelta(hours=h)) for h in (5, 20, 60)]

    assert len(eligible(lot)) <= len(lot)


# ══ Le lead time est reconstruit, jamais stocké ════════════════════════════
def test_le_temps_d_avance_est_reconstruit_sans_migration():
    """L'identité canonique porte déjà le coup d'envoi : dupliquer cette
    information l'exposerait à diverger d'elle-même."""
    verdict = evaluate(_obs(ObservationPhase.DECISION, avant=timedelta(hours=6)))

    assert verdict.lead_time == timedelta(hours=6)
    assert verdict.lead_minutes == pytest.approx(360.0)


# ══ Bout en bout : la maturité ne voit que l'admissible ════════════════════
def test_la_maturite_ne_consomme_que_des_observations_admissibles():
    import inspect

    from src.agents.quant.betting_engine import readiness_cli

    source = inspect.getsource(readiness_cli.observations_collectees)

    assert "eligible" in source
