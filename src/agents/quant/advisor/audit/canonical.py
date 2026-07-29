"""Sérialisation canonique + checksum de l'audit (Lot 10 §5/§6). RÉUTILISE la
primitive publique du Lot 1 (`domain.serialization`) — aucune seconde convention.

`to_json` garantit : clés triées, `Decimal` -> chaîne, `Enum` -> valeur publique,
`Mapping` déterministe, `frozenset` trié, aucun `float` monétaire résiduel, UTF-8
déterministe, indépendance à l'ordre d'insertion. Fonctionne sur un objet du
domaine COMME sur un dict déjà désérialisé (mêmes octets)."""

from __future__ import annotations

import hashlib

from ..domain import serialization


def canonical_serialize(obj) -> str:
    return serialization.to_json(obj)


def checksum(obj) -> str:
    return hashlib.sha256(canonical_serialize(obj).encode("utf-8")).hexdigest()
