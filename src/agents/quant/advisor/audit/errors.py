"""Erreurs d'audit STABLES (Lot 10). Aucun fallback silencieux : toute corruption,
version inconnue, collision ou audit incomplet lève une erreur structurée portant
un code stable (jamais une réparation implicite)."""

from __future__ import annotations


class AuditError(Exception):
    code = "AUDIT_ERROR"


class InvalidAuditJson(AuditError):
    code = "INVALID_AUDIT_JSON"


class UnknownAuditSchemaVersion(AuditError):
    code = "UNKNOWN_AUDIT_SCHEMA_VERSION"


class AuditIncomplete(AuditError):
    code = "AUDIT_INCOMPLETE"


class AuditChecksumMismatch(AuditError):
    code = "AUDIT_CHECKSUM_MISMATCH"


class ConfigSnapshotCorrupt(AuditError):
    code = "CONFIG_SNAPSHOT_CORRUPT"


class DuplicateAuditDivergent(AuditError):
    code = "DUPLICATE_AUDIT_DIVERGENT"


class RequestIdContentMismatch(AuditError):
    code = "REQUEST_ID_CONTENT_MISMATCH"


class AuditNotFound(AuditError):
    code = "AUDIT_NOT_FOUND"
