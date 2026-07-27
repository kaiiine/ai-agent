"""Décision de valeur par sélection (§8) + garde-fous.

Cap dur BE-FR-011 : un modèle non `SUPPORTED` ne peut JAMAIS produire `BET`
(quel que soit l'EV, la cote, la qualité des données). L'EV/no-vig sont calculés
pour l'audit mais la décision est plafonnée à `ABSTAIN` / `MODEL_NOT_SUPPORTED`.
En V0, tous les modèles étant EXPERIMENTAL, la sortie est toujours `ABSTAIN`.

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
    model_reliability: float | None             # issu de calibration/ (absent -> None)
    # Métriques d'audit — None si evaluation_status == NOT_EVALUATED (jamais 0).
    implied_probability_raw: float | None
    no_vig_probability: float | None
    edge: float | None
    expected_value: float | None
    evaluation_status: EvaluationStatus
    decision: str                               # "BET" | "WATCH" | "ABSTAIN" (V0 : toujours ABSTAIN)
    reasons: list[str]


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
        model_reliability=None,                  # calibration/ non construit
    )


def evaluate_selection(
    prediction: MarketPrediction, market_odds: Sequence[OddsSnapshot]
) -> BettingDecision:
    target = next((o for o in market_odds if o.selection == prediction.selection), None)

    # Offre boostée : refus AVANT toute validation/évaluation (ADR-017, Vague 2).
    # Prioritaire sur la cohérence : un boosté peut être une sélection isolée (pas
    # un marché 1X2 complet) ; on ne calcule rien, donc pas besoin d'un no-vig.
    if target is not None and target.is_boosted:
        return BettingDecision(
            **_base(prediction, target), implied_probability_raw=None,
            no_vig_probability=None, edge=None, expected_value=None,
            evaluation_status=EvaluationStatus.NOT_EVALUATED,
            decision="ABSTAIN", reasons=["UNSUPPORTED_ODDS_TYPE"],
        )

    # Sinon, un marché cohérent et complet est requis pour évaluer.
    validate_market(market_odds, prediction)     # -> MarketCoherenceError si incohérent
    target = next(o for o in market_odds if o.selection == prediction.selection)

    model_p = prediction.fair_probability
    implied = round(margin_removal.implied_raw(target.decimal_odds), 4)
    no_vig_p = round(margin_removal.no_vig(market_odds)[prediction.selection], 4)
    expected = round(_ev(model_p, target.decimal_odds), 4)
    edge = round(model_p - no_vig_p, 4)

    reasons: list[str] = []
    if prediction.uncertainty_status == UncertaintyStatus.NOT_ESTIMATED:
        reasons.append("UNCERTAINTY_NOT_ESTIMATED")   # facteur de confiance, distinct du cap

    if prediction.calibration_status != DataReadiness.SUPPORTED:
        # Cap dur BE-FR-011 : rien ne le contourne.
        decision = "ABSTAIN"
        reasons.insert(0, "MODEL_NOT_SUPPORTED")
    else:
        # Chemin SUPPORTED (BET/WATCH) : exige calibration/ (model_reliability) et
        # une incertitude estimée (EV borne basse, BE-FR-012), non construits.
        # Inatteignable en V0 (aucun modèle SUPPORTED) -> échec bruyant si atteint.
        raise NotImplementedError(
            "chemin SUPPORTED non implémenté : nécessite calibration/ (model_reliability) "
            "et un EV à la borne basse (BE-FR-012)"
        )

    return BettingDecision(
        **_base(prediction, target), implied_probability_raw=implied,
        no_vig_probability=no_vig_p, edge=edge, expected_value=expected,
        evaluation_status=EvaluationStatus.EVALUATED,
        decision=decision, reasons=reasons,
    )
