"""Décision de valeur par sélection (§8) + garde-fous + money-path SUPPORTED (BE-FR-012).

Cap dur BE-FR-011 : un modèle non `SUPPORTED` ne peut JAMAIS produire `BET`
(quel que soit l'EV, la cote, la qualité des données). L'EV/no-vig sont calculés
pour l'audit mais la décision est plafonnée à `ABSTAIN` / `MODEL_NOT_SUPPORTED`.
Le modèle réel restant EXPERIMENTAL, la sortie réelle est toujours `ABSTAIN`.

Money-path SUPPORTED (ADR-BE-003, Option A) : le Betting Engine DÉCIDE `BET`/`ABSTAIN`
et EXPOSE l'économie (worst_case_ev, EV moyen, edge, no-vig, model_reliability,
data_quality) ; il NE SIZE PAS (le sizing Kelly vit dans Advisor, ADR-ADV-007 ;
PRD-BE §8.5 : « value_engine ne gère pas la bankroll ni le sizing »). `BET` exige,
sur un modèle SUPPORTED : un intervalle ESTIMÉ (sinon la borne basse n'existe pas),
data_quality ≥ seuil, model_reliability ≥ seuil, et `worst_case_ev = probability_low·odds − 1
≥ min_bet_ev` (BE-FR-012 : EV à la borne basse, jamais à la moyenne). Tout `BET`
reste une PROPOSITION (BE-FR-014) : aucun placement automatique.

Une offre boostée n'est jamais évaluée comme une cote standard : refus explicite
`ABSTAIN` / `UNSUPPORTED_ODDS_TYPE`, aucune métrique calculée (jamais 0 pour
« non calculé » : `evaluation_status=NOT_EVALUATED` et métriques `None`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from src.agents.quant.betting_engine.core.market_model import (
    DataReadiness,
    MarketPrediction,
    UncertaintyStatus,
)
from src.agents.quant.betting_engine.core.odds import OddsSnapshot

from . import margin_removal
from .bet_policy import BetDecisionPolicy, default_bet_decision_policy
from .expected_value import ev as _ev
from .market_coherence import validate_market


class EvaluationStatus(str, Enum):
    EVALUATED = "EVALUATED"          # métriques calculées (edge/EV/no-vig présents)
    NOT_EVALUATED = "NOT_EVALUATED"  # offre inéligible (ex. boostée) : métriques None


@dataclass(frozen=True)
class BettingDecision:
    selection: str
    bookmaker: str
    bookmaker_odds: float
    market_type: str
    model_probability: float
    probability_interval: tuple[float, float]   # propagé ; NON un intervalle fiable si NOT_ESTIMATED
    uncertainty_status: str
    data_quality: float
    calibration_status: str
    model_reliability: float | None             # exposé pour le sizing Advisor (None si non-SUPPORTED)
    # Métriques d'audit — None si evaluation_status == NOT_EVALUATED (jamais 0).
    implied_probability_raw: float | None
    no_vig_probability: float | None
    edge: float | None
    expected_value: float | None                # EV au point (moyen)
    evaluation_status: EvaluationStatus
    decision: str                               # "BET" | "WATCH" | "ABSTAIN"
    reasons: list[str]
    # Trace money-path (BE-FR-012) — None hors chemin SUPPORTED évalué.
    worst_case_ev: float | None = None          # EV à la borne basse (probability_low)
    min_bet_ev: float | None = None             # seuil appliqué (policy versionnée)


def _reject_invalid_probabilities(prediction: MarketPrediction) -> None:
    """Garde money-sensitive : sur le chemin SUPPORTED, des probabilités hors [0,1]
    ou un intervalle incohérent (`low <= fair <= high` violé) sont un contrat cassé
    -> `ValueError` explicite, jamais une décision réparée en silence (BE-FR-012)."""
    for name, p in (("fair", prediction.fair_probability),
                    ("low", prediction.probability_low),
                    ("high", prediction.probability_high)):
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"probabilité {name} hors [0,1] : {p}")
    if not (prediction.probability_low <= prediction.fair_probability <= prediction.probability_high):
        raise ValueError(
            "intervalle de probabilité incohérent : low <= fair <= high requis "
            f"(low={prediction.probability_low}, fair={prediction.fair_probability}, "
            f"high={prediction.probability_high})"
        )


def _base(prediction: MarketPrediction, target: OddsSnapshot) -> dict:
    return dict(
        selection=prediction.selection,
        bookmaker=target.bookmaker,
        bookmaker_odds=target.decimal_odds,
        market_type=target.market_type,
        model_probability=prediction.fair_probability,
        probability_interval=(prediction.probability_low, prediction.probability_high),
        uncertainty_status=prediction.uncertainty_status.value,
        data_quality=prediction.data_quality,
        calibration_status=prediction.calibration_status.value,
    )


def evaluate_selection(
    prediction: MarketPrediction,
    market_odds: Sequence[OddsSnapshot],
    *,
    policy: BetDecisionPolicy | None = None,
    expected_selections: frozenset[str] | None = None,
) -> BettingDecision:
    policy = policy or default_bet_decision_policy()
    target = next((o for o in market_odds if o.selection == prediction.selection), None)

    # Offre boostée : refus AVANT toute validation/évaluation (ADR-017, Vague 2).
    # Prioritaire sur la cohérence : un boosté peut être une sélection isolée (pas
    # un marché 1X2 complet) ; on ne calcule rien, donc pas besoin d'un no-vig.
    if target is not None and target.is_boosted:
        return BettingDecision(
            **_base(prediction, target), model_reliability=None, implied_probability_raw=None,
            no_vig_probability=None, edge=None, expected_value=None,
            evaluation_status=EvaluationStatus.NOT_EVALUATED,
            decision="ABSTAIN", reasons=["UNSUPPORTED_ODDS_TYPE"],
        )

    # Sinon, un marché cohérent et complet est requis pour évaluer.
    validate_market(market_odds, prediction, expected_selections=expected_selections)  # -> MarketCoherenceError
    target = next(o for o in market_odds if o.selection == prediction.selection)

    model_p = prediction.fair_probability
    implied = round(margin_removal.implied_raw(target.decimal_odds), 4)
    no_vig_p = round(margin_removal.no_vig(market_odds)[prediction.selection], 4)
    expected = round(_ev(model_p, target.decimal_odds), 4)
    edge = round(model_p - no_vig_p, 4)

    if prediction.calibration_status != DataReadiness.SUPPORTED:
        # Cap dur BE-FR-011 : rien ne le contourne. Comportement inchangé.
        reasons = ["MODEL_NOT_SUPPORTED"]
        if prediction.uncertainty_status == UncertaintyStatus.NOT_ESTIMATED:
            reasons.append("UNCERTAINTY_NOT_ESTIMATED")   # facteur de confiance, distinct du cap
        decision, reliability, worst_case_ev, min_bet_ev = "ABSTAIN", None, None, None
    else:
        # Money-path SUPPORTED (Option A) : gates -> BET/ABSTAIN, AUCUN sizing.
        _reject_invalid_probabilities(prediction)          # jamais réparé en silence (§19)
        min_bet_ev = policy.min_bet_ev
        reliability = policy.supported_model_reliability   # reliability V1 explicite (§7, ADR-BE-003)
        # BE-FR-012 : EV à la BORNE BASSE (probability_low), jamais à la moyenne.
        worst_case_ev = round(_ev(prediction.probability_low, target.decimal_odds), 4)
        reasons = []
        if prediction.uncertainty_status != UncertaintyStatus.ESTIMATED:
            # Sans intervalle estimé, probability_low == fair : pas de vraie borne basse
            # -> on refuse (jamais un BET sur la moyenne déguisée en borne basse).
            reasons.append("UNCERTAINTY_NOT_ESTIMATED")
        if prediction.data_quality < policy.min_data_quality:
            reasons.append("DATA_QUALITY_INSUFFICIENT")
        if reliability < policy.min_model_reliability:
            reasons.append("MODEL_RELIABILITY_INSUFFICIENT")
        if worst_case_ev < policy.min_bet_ev:
            reasons.append("VALUE_BELOW_THRESHOLD")
        decision = "ABSTAIN" if reasons else "BET"

    return BettingDecision(
        **_base(prediction, target), model_reliability=reliability,
        implied_probability_raw=implied, no_vig_probability=no_vig_p, edge=edge,
        expected_value=expected, evaluation_status=EvaluationStatus.EVALUATED,
        decision=decision, reasons=reasons,
        worst_case_ev=worst_case_ev, min_bet_ev=min_bet_ev,
    )
