"""Composants du score (ADR-ADV-005 D3). Fonctions pures, chacune bornée à `[0,1]`
(composants) ou `>= 0` (pénalités). Une donnée REQUIRED absente lève `NonRankable`
(rejet explicite) ; jamais de conversion silencieuse vers 0/1.

`uncertainty_penalty` : `CandidateBet` ne porte pas `uncertainty_status` ; le
ranking ne voit que des ELIGIBLE (⟹ SUPPORTED ⟹ incertitude ESTIMATED, BE-FR-012),
donc la largeur est un intervalle réel — width 0 = estimation serrée, jamais
« inconnu » (le cas NOT_ESTIMATED est exclu en amont par la frontière)."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from ..domain.money import ONE, ZERO
from ..policy import reason_codes
from .profiles import RankingProfile


class NonRankable(Exception):
    """Un candidat ELIGIBLE dont un input REQUIRED manque : porté par un reason
    code stable (jamais un score inventé)."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _unit(value: Decimal, name: str) -> Decimal:
    if not (ZERO <= value <= ONE):
        raise ValueError(f"{name} hors de [0,1] : {value}")
    return value


def value_component(expected_value_low: Decimal, profile: RankingProfile) -> Decimal:
    """Monotone ↗ de `expected_value_low`, linéaire bornée entre `ev_floor` et
    `ev_cap`. 0 = valeur pire-cas mesurée <= ev_floor (annulation intentionnelle)."""
    ratio = (expected_value_low - profile.ev_floor) / (profile.ev_cap - profile.ev_floor)
    return _unit(min(ONE, max(ZERO, ratio)), "value_component")


def quality_component(data_quality: Decimal) -> Decimal:
    """= data_quality (déjà [0,1]). 0 = qualité mesurée nulle."""
    return _unit(data_quality, "quality_component")


def freshness_component(freshness_score: Decimal | None, profile: RankingProfile) -> Decimal:
    """REQUIRED : `None` (ne devrait jamais atteindre le ranking) -> NonRankable."""
    if freshness_score is None:
        if profile.requires("freshness"):
            raise NonRankable(reason_codes.RANKING_MISSING_FRESHNESS)
        raise ValueError("freshness OPTIONAL sans politique définie en V1")
    return _unit(freshness_score, "freshness_component")


def reliability_component(
    model_maturity: str, calibration_score: Decimal | None, profile: RankingProfile,
) -> Decimal:
    """Fonction de la maturité (+ calibration si présente). Seul SUPPORTED atteint
    le ranking. `calibration_score` présent -> l'utiliser ; absent -> baseline
    documentée (ni 0 « jamais mesuré » ni 1 « parfait »)."""
    if model_maturity != "SUPPORTED":
        raise NonRankable(reason_codes.RANKING_MODEL_NOT_SUPPORTED)
    if calibration_score is not None:
        return _unit(calibration_score, "reliability_component")
    return _unit(profile.supported_baseline, "reliability_component")


def liquidity_component(liquidity_score: Decimal | None, profile: RankingProfile) -> Decimal:
    """OPTIONAL en V1 : présent -> l'utiliser ; `None` -> escompte conservateur
    documenté (`< 1`, `> 0`), jamais neutre ni retiré."""
    if liquidity_score is not None:
        return _unit(liquidity_score, "liquidity_component")
    return _unit(profile.liquidity_unknown_default, "liquidity_component")


def uncertainty_penalty(
    probability_low: Decimal, probability_high: Decimal, profile: RankingProfile,
) -> Decimal:
    """Pénalité >= 0 = poids × largeur d'intervalle. 0 = estimation serrée."""
    width = probability_high - probability_low
    if width < ZERO:
        raise ValueError(f"largeur d'intervalle négative : {width}")
    return profile.uncertainty_weight * width


def concentration_penalty(
    exposure_keys: frozenset[str], retained_exposure: Iterable[str], profile: RankingProfile,
) -> Decimal:
    """Pénalité >= 0 = poids × redondance avec les déjà-retenus. Redondance =
    part des clés d'exposition déjà couvertes. 0 = aucune redondance (rang 1).
    SÉQUENTIELLE/GLOUTONNE (dépend des retenus) — limitation V1 (ADR-ADV-005 D5)."""
    if not exposure_keys:
        return ZERO
    covered = sum(1 for k in exposure_keys if k in set(retained_exposure))
    redundancy = Decimal(covered) / Decimal(len(exposure_keys))
    return profile.concentration_weight * redundancy
