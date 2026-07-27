"""value_engine (§8) — évaluation de valeur INDÉPENDANTE par sélection.

Consomme `MarketPrediction` + les `OddsSnapshot` de toutes les issues du marché,
produit un `BettingDecision` (proba modèle, implicite brute, sans marge, edge,
EV, décision + raisons). Ne fait NI sizing, NI corrélation, NI parlay, NI
exposition portefeuille (-> portfolio/ / bet_ranking, étapes ultérieures).
"""

from .decision import BettingDecision, EvaluationStatus, evaluate_selection

__all__ = ["BettingDecision", "EvaluationStatus", "evaluate_selection"]
