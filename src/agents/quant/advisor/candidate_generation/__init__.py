"""Candidate Generator : normalise les évaluations adaptées en `CandidateBet`
(champs dérivés autorisés + id stable + clés d'exposition), sans créer aucune
donnée sportive ni décider de l'éligibilité."""

from .generator import candidate_from_evaluation, generate_candidates

__all__ = ["candidate_from_evaluation", "generate_candidates"]
