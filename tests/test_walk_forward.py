"""Harness de rejeu expanding — mécanique (synthétique) + PREMIER RUN RÉEL FL1.

Le run réel n'utilise QUE la fixture FL1 réelle committée (données réelles). Le
synthétique sert uniquement à tester la mécanique du framework.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
from src.agents.quant.gateway.core.identity_data import TEAMS
from src.agents.quant.gateway.sports.football.canonical_facts import CanonicalMatch
from src.agents.quant.betting_engine.sports.football.market_models.one_x_two import OneXTwoModel
from src.agents.quant.betting_engine.calibration.historical_dataset import (
    FL1_LEAGUE_ID,
    FL1_SEASON,
    load_fl1_2025,
)
from src.agents.quant.betting_engine.calibration.walk_forward import (
    WalkForwardRun,
    build_experiment_result,
    build_metrics,
    run_walk_forward,
)

# Empreinte du corpus COMPLET (2023-24 + 2024-25 + 2025-26). Elle a changé lors
# de l'acquisition historique, et c'est exactement son rôle : elle ancre la
# reproductibilité d'un run à un corpus donné. Une empreinte qui ne bougerait pas
# en changeant les données ne prouverait rien.
_FL1_FINGERPRINT = "sha256:f7e27883b6cd3aad3abc20eb1588fa9514c6ac0f1e7a35913f0005b0f7d37885"

_LEAGUE = "competition:football:fra:ligue1"
_A, _B, _C, _D = (f"team:football:fra:{t}" for t in ("psg", "marseille", "lyon", "lille"))


def _m(hid, aid, gh, ga, day):
    kickoff = datetime(2025, 8, day, 17, tzinfo=timezone.utc)
    return CanonicalMatch(f"m{hid}{aid}{day}", _LEAGUE, "2025", hid, aid, kickoff, "FINISHED", gh, ga)


def _synthetic_season():
    return [
        _m(_A, _B, 2, 0, 1), _m(_C, _D, 1, 1, 2),      # J1 : aucun antérieur -> exclus
        _m(_A, _C, 1, 0, 8), _m(_B, _D, 0, 2, 9),      # J2
        _m(_A, _D, 3, 1, 15), _m(_B, _C, 1, 1, 16),    # J3
    ]


# ── Mécanique du harness ──────────────────────────────────────────────────────
def test_harness_excludes_matches_without_prior_form():
    run = run_walk_forward(_synthetic_season(), OneXTwoModel(), _LEAGUE, "2025")
    assert run.n_total == 6
    assert run.exclusions.get("INSUFFICIENT_DATA_no_prior_form") == 2   # les 2 matchs de J1
    assert run.n_evaluated == 4


def test_harness_prediction_is_point_in_time_leak_free():
    full = _synthetic_season()
    # Retirer le DERNIER match ne doit rien changer à la 1re prédiction évaluée
    # (celle-ci ne dépend que de matchs strictement antérieurs).
    p_full = run_walk_forward(full, OneXTwoModel(), _LEAGUE, "2025").model_predictions[0]
    p_short = run_walk_forward(full[:-1], OneXTwoModel(), _LEAGUE, "2025").model_predictions[0]
    assert p_full == p_short


def test_harness_never_produces_supported():
    run = run_walk_forward(_synthetic_season(), OneXTwoModel(), _LEAGUE, "2025")
    result = build_experiment_result(run, OneXTwoModel(), "sha256:x", "rev")
    assert result.experiment_status == "CANDIDATE_FOR_REVIEW"
    assert result.experiment_status != "SUPPORTED"


def test_status_reflects_validity_not_performance():
    # Un run VALIDE où le modèle PERD nettement contre les baselines (toujours 0.9
    # home alors que l'issue est away) doit produire le MÊME CANDIDATE_FOR_REVIEW :
    # le statut = validité, jamais un jugement de performance.
    losing = [({"home": 0.9, "draw": 0.05, "away": 0.05}, "away") for _ in range(10)]
    run = WalkForwardRun(losing, losing, n_total=12, n_evaluated=10,
                         exclusions={"x": 2}, evaluation_start="s", evaluation_end="e")
    assert build_metrics(run)["beats_uniform_brier"] is False      # il perd bien
    result = build_experiment_result(run, OneXTwoModel(), "sha", "rev")
    assert result.experiment_status == "CANDIDATE_FOR_REVIEW"       # statut inchangé


def test_empty_run_is_failed_not_candidate():
    run = WalkForwardRun([], [], n_total=5, n_evaluated=0,
                         exclusions={"x": 5}, evaluation_start="s", evaluation_end="e")
    assert build_experiment_result(run, OneXTwoModel(), "sha", "rev").experiment_status == "FAILED"


# ── PREMIER RUN RÉEL : 305 matchs Ligue 1 2025-26 ─────────────────────────────
def test_first_real_fl1_run():
    resolver = IdentityResolver(TEAMS)
    matches, fingerprint, n_finished = load_fl1_2025(resolver)

    # 1) Invariants DATASET d'abord : si la fixture change, l'échec est ici (donnée
    #    modifiée), PAS sur les valeurs de métriques (fausse régression math).
    assert fingerprint == _FL1_FINGERPRINT
    # Corpus complet (3 saisons) : on vérifie l'INVARIANT de résolution et un
    # plancher, pas la taille d'une saison — la figer casserait le test à chaque
    # acquisition sans jamais détecter une perte.
    assert n_finished >= 305 and len(matches) == n_finished

    run = run_walk_forward(matches, OneXTwoModel(), FL1_LEAGUE_ID, FL1_SEASON)
    # Le cold-start reste la SEULE exclusion, et il ne concerne que les premières
    # journées de chaque saison : sa part chute de 9/305 à 13/916 avec
    # l'historique — mécaniquement, aucun paramètre n'ayant changé.
    assert run.n_evaluated + sum(run.exclusions.values()) == len(matches)
    assert set(run.exclusions) == {"INSUFFICIENT_DATA_no_prior_form"}

    # 2) Métriques ensuite, sur le dataset garanti identique.
    m = build_metrics(run)
    brier, ll = m["model"]["brier"]["value"], m["model"]["log_loss"]["value"]
    # Valeurs du corpus COMPLET (3 saisons). Elles ont bougé à l'acquisition —
    # Brier 0.6211 -> 0.6185, log-loss idem — et c'est ce qu'un benchmark doit
    # montrer. Ce qui ne doit jamais bouger est plus bas : battre les baselines.
    assert 0.617 < brier < 0.620
    assert 1.020 < ll < 1.035
    assert m["beats_uniform_brier"] is True
    assert brier < m["baselines"]["uniform"]["brier"]["value"]
    assert brier < m["baselines"]["prior_frequency"]["brier"]["value"]

    # Déterminisme (reproductibilité de l'expérience).
    assert build_metrics(run_walk_forward(matches, OneXTwoModel(), FL1_LEAGUE_ID, FL1_SEASON))["model"] == m["model"]

    # ExperimentResult : CANDIDATE_FOR_REVIEW (validité), jamais SUPPORTED.
    result = build_experiment_result(run, OneXTwoModel(), fingerprint, "testrev")
    assert result.experiment_status == "CANDIDATE_FOR_REVIEW"
    assert result.experiment_status != "SUPPORTED"
    assert result.metrics["model"]["brier"]["convention"] == "sum_over_classes"
