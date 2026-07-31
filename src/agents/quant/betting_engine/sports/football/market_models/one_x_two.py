"""MarketModel 1X2 football (MATCH_WINNER) — Poisson-Dixon-Coles, EXPERIMENTAL.

Prend `attack_strength`/`defense_strength` depuis `EventFeatureSet` (produites
par feature_engineering), applique domicile + correction Dixon-Coles au match
cible, et renvoie P(home)/P(draw)/P(away). Le noyau mathématique (`score_matrix`,
`market_probabilities`) est importé de `quant/dixon_coles.py` (import transitoire,
todo #7 — jamais copié).

Produit UNIQUEMENT des probabilités : ni EV, ni cotes, ni sizing, ni décision
(value_engine). Statut plafonné EXPERIMENTAL — aucun chemin ne rend SUPPORTED.
"""

from __future__ import annotations

from datetime import datetime

from src.agents.quant.dixon_coles import (
    DEFAULT_RHO,
    HOME_ADVANTAGE,
    market_probabilities,
    score_matrix,
)
from src.agents.quant.betting_engine.core.canonical_event import CanonicalEvent, CanonicalMarket
from src.agents.quant.betting_engine.core.errors import (
    InsufficientDataError,
    PointInTimeViolationError,
)
from src.agents.quant.betting_engine.core.feature_set import EventFeatureSet
from src.agents.quant.betting_engine.core.market_model import (
    FOOTBALL_1X2,
    DataReadiness,
    MarketPrediction,
    PredictionExplanation,
    UncertaintyStatus,
)


class OneXTwoModel:
    sport = "football"
    market_type = "MATCH_WINNER"
    model_name = "one_x_two"
    model_version = "football.one_x_two.dixon_coles.v0"
    schema = FOOTBALL_1X2                    # 3-way (home/draw/away) — pilote la canonicalisation/décision

    _REQUIRED = frozenset({"attack_strength", "defense_strength"})
    _SELECTIONS = ("home", "draw", "away")

    @property
    def _ceiling(self) -> DataReadiness:
        """Plafond de calibration DÉRIVÉ du ledger de support (support_status.py) —
        même source de vérité que manifest.GLOBAL_MODEL_STATUS. SUPPORTED seulement
        si un `ModelSupportDecision` SUPPORTED est persisté (aucun aujourd'hui ->
        EXPERIMENTAL). Jamais un littéral déclaratif, jamais SUPPORTED par défaut."""
        from src.agents.quant.betting_engine.support_status import resolve_market_status
        return resolve_market_status(self.model_name, self.model_version)

    # -- contrat MarketModel --------------------------------------------------
    def required_features(self) -> set[str]:
        return set(self._REQUIRED)

    def assess_data_readiness(
        self, event: CanonicalEvent, features: EventFeatureSet
    ) -> DataReadiness:
        by_role = {p.role: p.canonical_id for p in event.participants}
        if "home" not in by_role or "away" not in by_role:
            return DataReadiness.INSUFFICIENT_DATA
        for role in ("home", "away"):
            pf = features.participant_features.get(by_role[role], {})
            if not self._REQUIRED <= set(pf):
                # attack/defense absentes => forme totalement absente (form:{cid}).
                return DataReadiness.INSUFFICIENT_DATA
        # Données présentes -> plafonné au statut dérivé du ledger (EXPERIMENTAL
        # tant qu'aucun ModelSupportDecision SUPPORTED n'est persisté).
        return self._ceiling

    def predict(
        self,
        event: CanonicalEvent,
        market: CanonicalMarket,
        features: EventFeatureSet,
        point_in_time: datetime,
    ) -> MarketPrediction:
        if market.market_type != self.market_type:
            raise ValueError(
                f"OneXTwoModel ne couvre que {self.market_type}, reçu {market.market_type}"
            )
        if market.selection not in self._SELECTIONS:
            raise ValueError(
                f"sélection inconnue pour 1X2 : {market.selection!r} (attendu {self._SELECTIONS})"
            )
        return self._predict_all(event, features, point_in_time)[market.selection]

    def predict_selections(
        self, event: CanonicalEvent, features: EventFeatureSet, point_in_time: datetime
    ) -> dict[str, MarketPrediction]:
        """Les trois issues 1/X/2 d'une MÊME matrice (cohérentes, somme ≈ 1)."""
        return self._predict_all(event, features, point_in_time)

    # -- interne --------------------------------------------------------------
    def _predict_all(
        self, event: CanonicalEvent, features: EventFeatureSet, point_in_time: datetime
    ) -> dict[str, MarketPrediction]:
        self._guard(event, features, point_in_time)

        by_role = {p.role: p.canonical_id for p in event.participants}
        home_str = self._strengths(features, by_role["home"])
        away_str = self._strengths(features, by_role["away"])
        matrix = score_matrix(home_str, away_str, DEFAULT_RHO)
        probs = market_probabilities(matrix)

        readiness = self.assess_data_readiness(event, features)     # EXPERIMENTAL
        data_quality = self._data_quality(event, features)
        explanation = self._explanation(event, features, matrix, home_str, away_str)

        return {
            selection: MarketPrediction(
                sport=self.sport,
                market_type=self.market_type,
                selection=selection,
                fair_probability=probs[selection],
                # Pas d'intervalle fondé au stade EXPERIMENTAL : on répète le point,
                # signalé NOT_ESTIMATED (absence d'intervalle, pas un intervalle nul).
                probability_low=probs[selection],
                probability_high=probs[selection],
                uncertainty_status=UncertaintyStatus.NOT_ESTIMATED,
                model_version=self.model_version,
                data_quality=data_quality,
                calibration_status=readiness,
                point_in_time=point_in_time,
                explanation=explanation,
            )
            for selection in self._SELECTIONS
        }

    def _guard(
        self, event: CanonicalEvent, features: EventFeatureSet, point_in_time: datetime
    ) -> None:
        if point_in_time is None:
            raise ValueError(
                "point_in_time obligatoire (ADR-004) — aucune substitution par l'heure courante"
            )
        readiness = self.assess_data_readiness(event, features)
        if readiness in (DataReadiness.INSUFFICIENT_DATA, DataReadiness.UNSUPPORTED):
            raise InsufficientDataError(
                f"readiness={readiness.value} : aucune probabilité produite pour {event.event_id}"
            )
        if features.as_of > point_in_time:
            raise PointInTimeViolationError(
                f"features.as_of={features.as_of.isoformat()} > "
                f"point_in_time={point_in_time.isoformat()} : donnée postérieure à la décision"
            )

    @staticmethod
    def _strengths(features: EventFeatureSet, canonical_id: str) -> dict:
        pf = features.participant_features[canonical_id]
        return {"attack": pf["attack_strength"], "defense": pf["defense_strength"]}

    @staticmethod
    def _expected_goals(matrix: list[list[float]]) -> tuple[float, float]:
        home = sum(x * p for x, row in enumerate(matrix) for p in row)
        away = sum(y * p for row in matrix for y, p in enumerate(row))
        return round(home, 4), round(away, 4)

    def _data_quality(self, event: CanonicalEvent, features: EventFeatureSet) -> float:
        quality = 1.0
        for participant in event.participants:
            cid = participant.canonical_id
            if f"form_insufficient:{cid}" in features.missing_features:
                quality -= 0.25
            if f"standings:{cid}" in features.missing_features:
                quality -= 0.15
        return round(max(quality, 0.0), 3)

    def _explanation(
        self,
        event: CanonicalEvent,
        features: EventFeatureSet,
        matrix: list[list[float]],
        home_str: dict,
        away_str: dict,
    ) -> PredictionExplanation:
        e_home, e_away = self._expected_goals(matrix)
        # Quantités RÉELLES du modèle + valeurs — pas des « importances » (DC n'en calcule pas).
        top_features = [
            ("home_expected_goals", e_home),
            ("away_expected_goals", e_away),
            ("home_attack_strength", float(home_str["attack"])),
            ("home_defense_strength", float(home_str["defense"])),
            ("away_attack_strength", float(away_str["attack"])),
            ("away_defense_strength", float(away_str["defense"])),
            ("home_advantage", float(HOME_ADVANTAGE)),
        ]

        by_role = {p.role: p.canonical_id for p in event.participants}
        warnings: list[str] = []
        for role in ("home", "away"):
            cid = by_role[role]
            if f"form_insufficient:{cid}" in features.missing_features:
                n = features.participant_features[cid].get("form_matches", "?")
                warnings.append(
                    f"historique insuffisant pour {cid} ({n} matchs) : "
                    "forces tirées vers la moyenne ligue (shrinkage)"
                )
            if f"standings:{cid}" in features.missing_features:
                warnings.append(
                    f"classement indisponible pour {cid} : ajustement adversaire désactivé (fallback)"
                )
        warnings.append(
            f"correction Dixon-Coles active sur les scores faibles (rho={DEFAULT_RHO})"
        )
        warnings.append(
            "data_timeliness=current_snapshot : forme/classement gateway = snapshot courant, "
            "pas reconstruit point-in-time (non backtestable, ADR-004)"
        )

        confidence_drivers = [
            "aucun intervalle prédictif calibré (EXPERIMENTAL, pas de walk-forward) : "
            "probability_low=high=fair_probability, uncertainty_status=NOT_ESTIMATED — "
            "absence d'intervalle, pas un intervalle nul",
            "Dixon-Coles ne décompose pas de contribution par feature : "
            "top_features sont des intensités/forces du modèle, pas des importances statistiques",
            "rho Dixon-Coles = valeur du papier (défaut), non ré-estimée sur le championnat",
        ]
        if any(
            f"form_insufficient:{by_role[r]}" in features.missing_features
            for r in ("home", "away")
        ):
            confidence_drivers.append(
                "faible échantillon : shrinkage vers la moyenne ligue — incertitude réelle plus large"
            )

        return PredictionExplanation(
            top_features=top_features,
            missing_features=set(features.missing_features),
            warnings=warnings,
            confidence_drivers=confidence_drivers,
        )
