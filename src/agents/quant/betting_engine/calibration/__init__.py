"""calibration/ (§7.1) — machinerie générique de rejeu point-in-time et métriques.

Rejeu CHRONOLOGIQUE point-in-time à paramètres FIXES (pas d'entraînement : rho,
shrinkage, home_advantage sont codés en dur). Produit des `ExperimentResult`
reproductibles ; ne modifie JAMAIS le statut d'un modèle (ExperimentResult ≠
ModelSupportDecision) — aucun passage automatique à SUPPORTED.
"""
