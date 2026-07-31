"""Registre DÉCLARATIF des modèles sportifs VALIDÉS (wave 3 §20/§24/§28).

Source de vérité de la « model coverage » : quels (sport, market) possèdent un modèle
réellement validé hors échantillon. DISTINCT de la couverture catalogue (ce que Winamax
expose) et de la maturité (dérivée du ledger). N'inclut QUE des modèles dont le skill a
été mesuré (jamais un sport ajouté par optimisme). Un sport découvert sur Winamax mais
absent d'ici est `SPORT_DISCOVERED_MODEL_UNAVAILABLE` — visible, jamais silencieux.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidatedSportModel:
    sport: str                 # clé sport canonique
    winamax_sport_id: int      # sportId Winamax (source = catalogue live)
    market_type: str
    outcomes: int              # 2 (moneyline) | 3 (1X2)
    model_name: str
    model_version: str
    methodology: str           # "dixon_coles" | "pairwise_elo"


# Modèles dont le skill est MESURÉ hors échantillon (cf. tests + readiness).
VALIDATED_MODELS: dict[str, ValidatedSportModel] = {
    "football": ValidatedSportModel(
        "football", 1, "MATCH_WINNER", 3, "one_x_two", "football.one_x_two.dixon_coles.v0", "dixon_coles"),
    "basketball": ValidatedSportModel(
        "basketball", 2, "MATCH_WINNER", 2, "basketball_moneyline", "basketball.moneyline.elo.v0", "pairwise_elo"),
    "baseball": ValidatedSportModel(
        "baseball", 3, "MATCH_WINNER", 2, "baseball_moneyline", "baseball.moneyline.elo.v0", "pairwise_elo"),
    "american_football": ValidatedSportModel(
        "american_football", 16, "MATCH_WINNER", 2, "american_football_moneyline", "nfl.moneyline.elo.v0", "pairwise_elo"),
    "volleyball": ValidatedSportModel(
        "volleyball", 23, "MATCH_WINNER", 2, "volleyball_moneyline", "volleyball.moneyline.elo.v0", "pairwise_elo"),
}

BY_WINAMAX_SPORT_ID: dict[int, ValidatedSportModel] = {
    m.winamax_sport_id: m for m in VALIDATED_MODELS.values()
}


def model_maturity(model: ValidatedSportModel) -> str:
    """Maturité DÉRIVÉE du ledger (jamais déclarative) : EXPERIMENTAL tant qu'aucun
    `ModelSupportDecision` SUPPORTED n'est persisté pour ce (model_name, model_version)."""
    from ..support_status import resolve_market_status
    return resolve_market_status(model.model_name, model.model_version).value
