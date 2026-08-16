"""Boucle fermée : ce que le modèle a annoncé, puis ce qui est réellement arrivé.

La CLV mesure le mouvement de la cote, l'audit archive la décision — ni l'un ni
l'autre ne dit si le modèle a eu raison. C'est ce que ce paquet ajoute.
"""

from .calibration import CalibrationReelle, calibration_reelle, rendre_texte
from .record import Issue, PredictionRecord
from .settlement import RaisonNonReglee, Reglement, regler_tennis
from .store import JsonlPredictionStore

__all__ = [
    "CalibrationReelle", "Issue", "JsonlPredictionStore", "PredictionRecord",
    "RaisonNonReglee", "Reglement", "calibration_reelle", "regler_tennis",
    "rendre_texte",
]
