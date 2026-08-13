"""Outil d'évaluation de maturité : exécute le walk-forward RÉEL, agrège les
observations hors échantillon, et produit un `ModelSupportDecision` MÉCANIQUE.

C'est le « rapport de readiness » du cas B (données insuffisantes) : il rend la
promotion future une simple conséquence de nouvelles données, pas un nouveau
chantier. Aucune métrique n'est fabriquée ; la CLV vient de l'`odds_history`
réel (vide -> NOT_YET_MEASURABLE) ; la freshness live est déclarée par l'appelant
(non wirée au point de décision -> NOT_MEASURABLE).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .calibration import metrics
from .calibration.walk_forward import WalkForwardRun, build_metrics, run_walk_forward
from .clv import OddsObservation, clv_readiness
from .live_coverage import live_freshness_capability
from .maturity import (
    FRESHNESS_MEASURABLE,
    FRESHNESS_NOT_MEASURABLE,
    MaturityObservations,
    MaturityPolicy,
    ModelSupportDecision,
    evaluate_maturity,
    load_maturity_policy,
)


@dataclass(frozen=True)
class MaturityAssessment:
    decision: ModelSupportDecision
    run: WalkForwardRun
    metrics: dict
    observations: MaturityObservations


def _per_fold_brier(run: WalkForwardRun) -> dict[str, float]:
    groups: dict[str, list] = defaultdict(list)
    for (probs, outcome), kickoff in zip(run.model_predictions, run.fold_kickoffs):
        groups[kickoff[:7]].append((probs, outcome))     # regroupe par mois "YYYY-MM"
    return {month: metrics.evaluate(preds)["brier"]["value"] for month, preds in groups.items()}


def assess_one_x_two_maturity(
    *,
    matches,
    model,
    league_id: str,
    season: str,
    odds_observations: Sequence[OddsObservation] = (),
    live_freshness_status: str = FRESHNESS_NOT_MEASURABLE,
    policy: MaturityPolicy | None = None,
) -> MaturityAssessment:
    policy = policy or load_maturity_policy()
    run = run_walk_forward(matches, model, league_id, season)
    m = build_metrics(run)

    fold_briers = _per_fold_brier(run)
    fold_spread = (max(fold_briers.values()) - min(fold_briers.values())) if len(fold_briers) >= 2 else None
    raw_ece = m["calibration"]["raw"]["ece"]["ece"]
    best_baseline = min(
        m["baselines"]["uniform"]["brier"]["value"],
        m["baselines"]["prior_frequency"]["brier"]["value"],
    )
    coverage = (run.n_evaluated / run.n_total) if run.n_total else None
    mean_dq = (sum(run.data_qualities) / len(run.data_qualities)) if run.data_qualities else None

    readiness = clv_readiness(list(odds_observations),
                              confidence=policy.criteria["clv_confidence_level"])

    observations = MaturityObservations(
        n_evaluated=run.n_evaluated,
        n_temporal_folds=m["temporal_folds"]["n_folds"],
        calibration_error=raw_ece,
        model_brier=m["model"]["brier"]["value"],
        best_baseline_brier=best_baseline,
        data_coverage=round(coverage, 4) if coverage is not None else None,
        mean_data_quality=round(mean_dq, 4) if mean_dq is not None else None,
        fold_brier_spread=round(fold_spread, 4) if fold_spread is not None else None,
        clv_status=readiness.status,
        clv_mean=readiness.mean_clv,                     # Decimal ou None — jamais 0
        clv_n_events=readiness.n_events,                 # échantillon EFFECTIF (§4)
        clv_lower_bound=readiness.clv_lower_bound,        # borne de confiance inférieure
        live_freshness_status=live_freshness_status,
    )
    decision = evaluate_maturity(
        model_name=model.model_name,
        model_version=model.model_version,
        observations=observations,
        policy=policy,
    )
    return MaturityAssessment(decision=decision, run=run, metrics=m, observations=observations)


def assess_default_one_x_two(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Évaluation sur le dataset réel embarqué (Ligue 1 2025-26). Rapport de readiness
    reproductible : charge la fixture réelle, exécute le walk-forward, verdict mécanique."""
    from src.agents.quant.gateway.core.identity_data import TEAMS
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
    from .calibration.historical_dataset import FL1_LEAGUE_ID, FL1_SEASON, load_fl1_2025
    from .sports.football.market_models.one_x_two import OneXTwoModel

    resolver = IdentityResolver(TEAMS)
    matches, _fingerprint, _n_finished = load_fl1_2025(resolver)
    return assess_one_x_two_maturity(
        matches=matches, model=OneXTwoModel(),
        league_id=FL1_LEAGUE_ID, season=FL1_SEASON,
        odds_observations=odds_observations,
        # MESURÉE, jamais déclarée : la capacité se lit sur la chaîne de providers
        # de la Gateway. Écrite en littéral, elle affirmait un PASS que cinq sports
        # ne pouvaient pas honorer. Distincte de la CLV, qui reste
        # NOT_YET_MEASURABLE faute de DONNÉES collectées.
        live_freshness_status=live_freshness_capability(FL1_LEAGUE_ID),
    )


def _assess_competition(loader, league_id, season, odds_observations) -> MaturityAssessment:
    """Générique — MÊME modèle (OneXTwoModel), MÊME walk-forward, sur le dataset réel
    d'une compétition. Verdict MÉCANIQUE : une compétition onboardée reste EXPERIMENTAL
    tant que les critères ne passent pas. L'onboarding ajoute des DONNÉES, jamais de la
    maturité — aucune promotion manuelle, aucune nouvelle méthodologie."""
    from src.agents.quant.gateway.core.identity_data import TEAMS
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
    from .sports.football.market_models.one_x_two import OneXTwoModel

    resolver = IdentityResolver(TEAMS)
    matches, _fingerprint, _n_finished = loader(resolver)
    return assess_one_x_two_maturity(
        matches=matches, model=OneXTwoModel(),
        league_id=league_id, season=season,
        odds_observations=odds_observations,
        live_freshness_status=live_freshness_capability(league_id),
    )


def _assess_corpus_backfille(loader, league_id, season, odds_observations) -> MaturityAssessment:
    """Même modèle, même walk-forward, sur un corpus dont l'identité a été résolue
    en AMONT par `historical_discovery`.

    Le chargeur générique ci-dessus passe un `IdentityResolver` alimenté par les
    championnats onboardés ; une coupe d'Europe y perdrait la quasi-totalité de
    ses clubs. Le corpus backfillé arrive déjà canonique, avec sa provenance —
    d'où un chargeur qui n'attend pas de resolver. Rien d'autre ne change : ni le
    modèle, ni le harness, ni le verdict de maturité.
    """
    from .sports.football.market_models.one_x_two import OneXTwoModel

    matches, _fingerprint, _n_total = loader()
    return assess_one_x_two_maturity(
        matches=matches, model=OneXTwoModel(),
        league_id=league_id, season=season,
        odds_observations=odds_observations,
        live_freshness_status=live_freshness_capability(league_id),
    )


def assess_champions_league(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Ligue des Champions — 2 182 rencontres, trois providers dédoublonnés."""
    from .calibration.historical_dataset import CL_LEAGUE_ID, load_cl
    return _assess_corpus_backfille(load_cl, CL_LEAGUE_ID, "multi", odds_observations)


def assess_europa_league(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Ligue Europa — 814 rencontres, openfootball seul (CC0-1.0)."""
    from .calibration.historical_dataset import EL_LEAGUE_ID, load_el
    return _assess_corpus_backfille(load_el, EL_LEAGUE_ID, "multi", odds_observations)


def assess_conference_league(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Conference League — 575 rencontres, compétition créée en 2021."""
    from .calibration.historical_dataset import CONF_LEAGUE_ID, load_conf
    return _assess_corpus_backfille(load_conf, CONF_LEAGUE_ID, "multi", odds_observations)


def assess_serie_a(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Serie A 2025-26 (dataset réel football-data.org) — verdict mécanique EXPERIMENTAL."""
    from .calibration.historical_dataset import SA_LEAGUE_ID, SA_SEASON, load_sa_2025
    return _assess_competition(load_sa_2025, SA_LEAGUE_ID, SA_SEASON, odds_observations)


def assess_laliga(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """LaLiga 2025-26 (dataset réel football-data.org) — verdict mécanique EXPERIMENTAL."""
    from .calibration.historical_dataset import PD_LEAGUE_ID, PD_SEASON, load_pd_2025
    return _assess_competition(load_pd_2025, PD_LEAGUE_ID, PD_SEASON, odds_observations)


def assess_bundesliga(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Bundesliga (Allemagne) 2025-26 (dataset réel football-data.org) — mécanique EXPERIMENTAL."""
    from .calibration.historical_dataset import BL1_LEAGUE_ID, BL1_SEASON, load_bl1_2025
    return _assess_competition(load_bl1_2025, BL1_LEAGUE_ID, BL1_SEASON, odds_observations)


def assess_championship(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Championship anglaise 2025-26 (dataset réel football-data.org) — mécanique EXPERIMENTAL."""
    from .calibration.historical_dataset import ELC_LEAGUE_ID, ELC_SEASON, load_elc_2025
    return _assess_competition(load_elc_2025, ELC_LEAGUE_ID, ELC_SEASON, odds_observations)


def assess_eredivisie(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Eredivisie 2025-26 (dataset réel football-data.org) — mécanique EXPERIMENTAL."""
    from .calibration.historical_dataset import DED_LEAGUE_ID, DED_SEASON, load_ded_2025
    return _assess_competition(load_ded_2025, DED_LEAGUE_ID, DED_SEASON, odds_observations)


def assess_primeira_liga(odds_observations: Sequence[OddsObservation] = ()) -> MaturityAssessment:
    """Primeira Liga 2025-26 (dataset réel football-data.org) — mécanique EXPERIMENTAL."""
    from .calibration.historical_dataset import PPL_LEAGUE_ID, PPL_SEASON, load_ppl_2025
    return _assess_competition(load_ppl_2025, PPL_LEAGUE_ID, PPL_SEASON, odds_observations)
