"""Anti-leakage EXPLICITE (consigne §15/§16) : une donnée future TRÈS informative
existe mais ne doit JAMAIS influencer une prédiction antérieure — ni le modèle, ni
le calibrateur point-in-time.

Scénario : on injecte un match FUTUR aberrant (score 20-0, information massive sur
les forces d'équipe). S'il fuyait dans la reconstruction point-in-time, il
changerait radicalement les prédictions antérieures. Le gate `kickoff < cutoff`
(STRICT) doit le rendre invisible pour tout ce qui précède.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from src.agents.quant.gateway.core.identity_data import TEAMS
from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch
from src.agents.quant.betting_engine.calibration.historical_dataset import (
    FL1_LEAGUE_ID,
    FL1_SEASON,
    load_fl1_2025,
)
from src.agents.quant.betting_engine.calibration.walk_forward import run_walk_forward
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel


def _subset(n: int = 80):
    resolver = IdentityResolver(TEAMS)
    matches, _fp, _n = load_fl1_2025(resolver)
    return sorted(matches, key=lambda m: m.kickoff)[:n]


def _extreme_future_match(subset) -> CanonicalMatch:
    """Match aberrant, POSTÉRIEUR à tout le sous-ensemble (20-0)."""
    last = subset[-1]
    return replace(
        last,
        canonical_match_id="FUTURE-LEAK-PROBE",
        kickoff=last.kickoff + timedelta(days=30),
        goals_home=20,
        goals_away=0,
    )


def test_future_informative_match_never_changes_earlier_model_predictions():
    subset = _subset()
    base = run_walk_forward(subset, OneXTwoModel(), FL1_LEAGUE_ID, FL1_SEASON)

    with_future = run_walk_forward(
        subset + [_extreme_future_match(subset)], OneXTwoModel(), FL1_LEAGUE_ID, FL1_SEASON
    )

    # Toutes les prédictions antérieures (mêmes matchs, même ordre) sont IDENTIQUES.
    n = len(base.model_predictions)
    assert with_future.model_predictions[:n] == base.model_predictions
    # Le match futur n'ajoute qu'une prédiction en fin (il a une forme antérieure).
    assert len(with_future.model_predictions) == n + 1


def test_future_informative_match_never_changes_earlier_calibrated_predictions():
    subset = _subset()
    base = run_walk_forward(subset, OneXTwoModel(), FL1_LEAGUE_ID, FL1_SEASON)
    with_future = run_walk_forward(
        subset + [_extreme_future_match(subset)], OneXTwoModel(), FL1_LEAGUE_ID, FL1_SEASON
    )
    n = len(base.calibrated_predictions)
    # Le calibrateur à T n'a vu que des paires kickoff < T : la future 20-0 est invisible.
    assert with_future.calibrated_predictions[:n] == base.calibrated_predictions


def test_flipping_a_future_outcome_does_not_change_earlier_calibration():
    """Preuve directe que le calibrateur n'utilise pas d'issues futures : on modifie
    l'ISSUE d'un match tardif ; aucune prédiction re-calibrée antérieure ne bouge."""
    subset = _subset(90)
    base = run_walk_forward(subset, OneXTwoModel(), FL1_LEAGUE_ID, FL1_SEASON)

    # Inverse l'issue du dernier match (home 5-0) : information future si elle fuyait.
    flipped = subset[:-1] + [replace(subset[-1], goals_home=5, goals_away=0)]
    other = run_walk_forward(flipped, OneXTwoModel(), FL1_LEAGUE_ID, FL1_SEASON)

    # Toutes les prédictions re-calibrées SAUF la dernière (celle du match modifié)
    # sont inchangées : le calibrateur ajusté à T ne consomme jamais l'issue de T ni
    # d'un match postérieur.
    assert other.calibrated_predictions[:-1] == base.calibrated_predictions[:-1]
