"""Portfolio Optimizer V1 : transforme des candidats classés ELIGIBLE en un
portefeuille primaire + alternatives multi-single (allocation gloutonne
déterministe, caps d'exposition, granularité). Réutilise la primitive de sizing
SINGLE, jamais une 2ᵉ formule."""

from .constraints import PortfolioCaps, load_portfolio_caps
from .optimizer import build_portfolios

__all__ = ["build_portfolios", "PortfolioCaps", "load_portfolio_caps"]
