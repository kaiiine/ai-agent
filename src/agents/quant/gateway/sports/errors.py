"""Exceptions du contrat SportModule (partagées, sans dépendance au registre)."""

from __future__ import annotations


class PayloadValidationError(Exception):
    """Levée par SportModule.validate_payload quand un payload ne respecte pas
    le schéma canonique courant du sport (GW-FR-007)."""
