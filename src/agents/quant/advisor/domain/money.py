"""Sécurité numérique des montants/cotes/probabilités (ADV-NFR-010, ADR-ADV-002).

Règle dure : aucun `float` dans les contrats. Un montant est `Decimal`, `int` ou
`str` (converti), **jamais** `float` — une conversion implicite float→Decimal
introduit une erreur de représentation silencieuse.

NB : ce module ne fixe PAS de politique d'arrondi/granularité (décision ouverte
PRD §27.10, ADR-ADV-002) — elle est différée au Lot 8 (allocation), là où des
montants sont réellement calculés. Ici, uniquement du typage et des bornes.
"""

from __future__ import annotations

from decimal import Decimal

ZERO = Decimal(0)
ONE = Decimal(1)

#: Granularité d'AFFICHAGE d'un montant en euros. Ne fixe aucune politique
#: d'arrondi de décision : elle sert aux montants dérivés présentés à
#: l'utilisateur, pour qu'ils aient une seule définition dans tout le produit.
CENT = Decimal("0.01")


def to_decimal(value, *, field: str = "montant") -> Decimal:
    """Convertit vers `Decimal` en refusant explicitement `float` (et `bool`)."""
    if isinstance(value, bool):
        raise TypeError(f"{field} : bool interdit")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        return Decimal(value)
    raise TypeError(f"{field} doit être Decimal/int/str, jamais {type(value).__name__} (ADV-NFR-010)")


def require_decimal(value, field: str) -> Decimal:
    """Exige un `Decimal` déjà construit (rejette float/bool/str) — pour __post_init__."""
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{field} doit être Decimal, reçu {type(value).__name__} (ADV-NFR-010, aucun float)")
    return value


def require_unit_interval(value: Decimal, field: str) -> Decimal:
    """Score/probabilité normalisé dans [0, 1]."""
    require_decimal(value, field)
    if not (ZERO <= value <= ONE):
        raise ValueError(f"{field} doit être dans [0, 1], reçu {value}")
    return value
