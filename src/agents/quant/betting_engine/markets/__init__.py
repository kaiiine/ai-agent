"""Inventaire multi-marché — observer, canonicaliser, vérifier la capacité.

Ce paquet s'arrête volontairement avant la modélisation, et donc très loin de la
recommandation. Il répond à « qu'est-ce qui existe et que savons-nous en faire »,
jamais à « que faut-il jouer ».
"""

from .capability import (
    CAPABILITIES,
    CapabilityResolution,
    CapabilityStatus,
    ModelCapability,
    register,
    resolve_model,
)
from .families import (
    ClassificationStatus,
    MarketClassification,
    MarketFamily,
    classify,
)
from .inventory import (
    NOT_MEASURED,
    InventoryRow,
    MarketCoverage,
    build_inventory,
    build_row,
    measure,
)
from .observation import (
    CLES_DE_PORTEE,
    CLES_DE_SUJET,
    CLES_OBSERVEES,
    RawMarketObservation,
    RawSelectionObservation,
    parser_parametres,
)

__all__ = [
    "CAPABILITIES", "CLES_DE_PORTEE", "CLES_DE_SUJET", "CLES_OBSERVEES",
    "CapabilityResolution", "CapabilityStatus", "ClassificationStatus",
    "InventoryRow", "MarketClassification", "MarketCoverage", "MarketFamily",
    "ModelCapability", "NOT_MEASURED", "RawMarketObservation",
    "RawSelectionObservation", "build_inventory", "build_row", "classify",
    "measure", "parser_parametres", "register", "resolve_model",
]
