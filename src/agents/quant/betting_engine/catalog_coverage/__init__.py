"""Couverture produit : quelle part du catalogue AXON sait-il évaluer ?

Complète `betting_engine/coverage.py`, qui mesure UN sport au niveau du moteur.
Ici c'est la vue d'un RUN entier, tous sports, persistée — la seule qui dise si
un onboarding a élargi la couverture ou seulement déplacé un blocage.
"""

from .metrics import NOT_MEASURED, CatalogCoverage, SportCoverage, mesurer, rendre_texte
from .store import JsonlCoverageStore

__all__ = ["NOT_MEASURED", "CatalogCoverage", "JsonlCoverageStore", "SportCoverage",
           "mesurer", "rendre_texte"]
