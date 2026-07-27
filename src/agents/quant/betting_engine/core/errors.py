"""Exceptions typées du betting-engine (miroir de `gateway/core/errors.py`).

Distinctes de `NoDataAvailableError` de la gateway : celle-ci signale une
**absence** de données ; celles-ci signalent qu'une prédiction ne peut pas être
produite honnêtement (données insuffisantes) ou qu'un contrat temporel a été
violé (donnée postérieure au point de décision).
"""

from __future__ import annotations


class InsufficientDataError(Exception):
    """`predict` a été appelé alors que les données requises manquent.

    Le modèle ne fabrique jamais de probabilités dans ce cas — le pré-check
    `assess_data_readiness` (INSUFFICIENT_DATA / UNSUPPORTED) doit être fait par
    l'appelant, qui s'abstient au lieu d'appeler `predict`.
    """


class PointInTimeViolationError(Exception):
    """Le feature set contient des données postérieures au `point_in_time`.

    `features.as_of > point_in_time` : la prédiction utiliserait de l'information
    non disponible au moment de la décision (fuite temporelle, ADR-004). On
    refuse plutôt que de produire une prédiction silencieusement biaisée.
    """


class MarketCoherenceError(Exception):
    """L'assemblage de cotes fourni au value_engine n'est pas un marché cohérent.

    Ensemble incomplet, sélections dupliquées/inconnues, cote ≤ 1, bookmakers ou
    événements différents, snapshots temporellement incompatibles, overround
    incohérent... On refuse : aucun no-vig ne doit être calculé sur un assemblage
    incomplet ou hétérogène.
    """
