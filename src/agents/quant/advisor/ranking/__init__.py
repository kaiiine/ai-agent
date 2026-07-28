"""Ranking Engine : classe les candidats ELIGIBLE hétérogènes (score multiplicatif
− pénalités), sans connaître leur sport. Profils versionnés, tri glouton
déterministe. Ne classe jamais les REVIEW_ONLY (ADR-ADV-005)."""

from .profiles import RankingProfile, load_ranking_profiles
from .sort import RankingResult, rank

__all__ = ["RankingProfile", "load_ranking_profiles", "RankingResult", "rank"]
