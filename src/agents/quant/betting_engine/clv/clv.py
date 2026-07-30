"""Closing-line value (CLV) POINT-IN-TIME — calcul réel si (et seulement si) une
paire décision/clôture existe pour le même marché ; sinon état explicite
`NOT_YET_MEASURABLE`. L'absence de CLV n'est JAMAIS convertie en 0 (consigne §9).

CLV = decision_odds / closing_odds − 1 :
  > 0  la cote prise à la décision était meilleure que la clôture (edge confirmé) ;
  = 0  identique ; < 0  la cote a monté en votre défaveur.

Contrainte point-in-time : `decision.observed_at < closing.observed_at` (STRICT) —
on ne « prouve » jamais une CLV avec une clôture antérieure à la décision.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .observation import ObservationPhase, OddsObservation

# Statuts explicites (repris tels quels par la politique de maturité).
MEASURABLE = "MEASURABLE"
NOT_YET_MEASURABLE = "NOT_YET_MEASURABLE"


@dataclass(frozen=True)
class ClvResult:
    market_key: tuple[str, str, str, str]
    decision_odds: Decimal
    closing_odds: Decimal
    decision_time: datetime
    closing_time: datetime
    clv: Decimal
    beat_close: bool


@dataclass(frozen=True)
class ClvReadiness:
    status: str                  # MEASURABLE | NOT_YET_MEASURABLE
    n_observations: int
    n_complete_pairs: int        # marchés ayant à la fois une DECISION et une CLOSING postérieure
    mean_clv: Decimal | None     # None si NOT_YET_MEASURABLE — jamais 0
    reason: str


def compute_clv(decision: OddsObservation, closing: OddsObservation) -> ClvResult:
    if decision.market_key != closing.market_key:
        raise ValueError("CLV : décision et clôture doivent viser le même marché")
    if decision.phase is not ObservationPhase.DECISION:
        raise ValueError("CLV : la première observation doit être de phase DECISION")
    if closing.phase is not ObservationPhase.CLOSING:
        raise ValueError("CLV : la seconde observation doit être de phase CLOSING")
    if not decision.observed_at < closing.observed_at:
        raise ValueError(
            "CLV : violation point-in-time — la clôture doit être STRICTEMENT postérieure "
            "à la décision"
        )
    clv = decision.decimal_odds / closing.decimal_odds - Decimal("1")
    return ClvResult(
        market_key=decision.market_key,
        decision_odds=decision.decimal_odds,
        closing_odds=closing.decimal_odds,
        decision_time=decision.observed_at,
        closing_time=closing.observed_at,
        clv=clv,
        beat_close=clv > 0,
    )


def clv_readiness(observations: Sequence[OddsObservation]) -> ClvReadiness:
    """Détermine si la CLV est mesurable à partir des observations collectées.

    MEASURABLE seulement s'il existe au moins un marché avec une DECISION ET une
    CLOSING strictement postérieure. Sinon NOT_YET_MEASURABLE (mean_clv=None, jamais 0).
    """
    by_market: dict[tuple, list[OddsObservation]] = defaultdict(list)
    for obs in observations:
        by_market[obs.market_key].append(obs)

    results: list[ClvResult] = []
    for market_key, obs_list in by_market.items():
        decisions = [o for o in obs_list if o.phase is ObservationPhase.DECISION]
        closings = [o for o in obs_list if o.phase is ObservationPhase.CLOSING]
        for d in decisions:
            later = [c for c in closings if d.observed_at < c.observed_at]
            if not later:
                continue
            closing = min(later, key=lambda c: c.observed_at)   # première clôture après la décision
            results.append(compute_clv(d, closing))

    if not results:
        return ClvReadiness(
            status=NOT_YET_MEASURABLE,
            n_observations=len(observations),
            n_complete_pairs=0,
            mean_clv=None,                    # jamais 0 pour « non mesuré »
            reason="aucune paire décision/clôture appariable (odds_history en collecte)",
        )
    mean_clv = sum((r.clv for r in results), Decimal("0")) / Decimal(len(results))
    return ClvReadiness(
        status=MEASURABLE,
        n_observations=len(observations),
        n_complete_pairs=len(results),
        mean_clv=mean_clv,
        reason=f"{len(results)} paire(s) décision/clôture mesurée(s)",
    )
