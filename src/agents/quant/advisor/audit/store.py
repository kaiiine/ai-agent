"""Store d'audit JSONL append-only (Lot 10 §1/§11/§19/§20). Une enveloppe JSON
canonique par ligne. Encapsulé derrière une frontière propre : un backend
différent (SQLite, base Axon...) pourra le remplacer sans toucher au domaine.

Reader STRICT : JSON invalide, version inconnue, checksum incorrect, champ
absent, doublon contradictoire du même audit_id -> erreur stable (jamais de
réparation silencieuse). Concurrence multi-processus : hors scope V1 (documenté)."""

from __future__ import annotations

import json
import pathlib

from . import canonical
from .errors import (
    AuditChecksumMismatch,
    AuditIncomplete,
    AuditNotFound,
    DuplicateAuditDivergent,
    InvalidAuditJson,
    RequestIdContentMismatch,
    UnknownAuditSchemaVersion,
)
from .schema import AUDIT_SCHEMA_VERSION, AdvisorAuditEnvelope

_REQUIRED = ("audit_schema_version", "audit_id", "request_id", "request_fingerprint",
            "payload_checksum", "payload")


class JsonlAuditStore:
    def __init__(self, path: pathlib.Path | str):
        self.path = pathlib.Path(path)

    # ── écriture append-only + idempotence ────────────────────────────────────
    def append(self, envelope: AdvisorAuditEnvelope) -> None:
        for raw in self._iter_raw():
            # Même request_id (identité d'appel censée unique, §0) mais contenu
            # métier différent -> collision logique explicite, jamais écrasée.
            if (raw.get("request_id") == envelope.request_id
                    and raw.get("request_fingerprint") != envelope.request_fingerprint):
                raise RequestIdContentMismatch(
                    f"request_id réutilisé pour un contenu métier différent : {envelope.request_id}")
        existing = self._find_raw(envelope.audit_id)
        if existing is not None:
            if existing["payload_checksum"] == envelope.payload_checksum:
                return                                   # idempotent : même décision logique
            raise DuplicateAuditDivergent(              # même audit_id, payload divergent
                f"audit_id déjà présent avec un contenu divergent : {envelope.audit_id}")
        line = canonical.canonical_serialize(envelope)   # ligne canonique complète
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # ── lecture stricte ───────────────────────────────────────────────────────
    def get(self, audit_id: str) -> dict:
        found = self._find_raw(audit_id)
        if found is None:
            raise AuditNotFound(audit_id)
        return self._validate(found)

    def iter_records(self):
        for raw in self._iter_raw():
            yield self._validate(raw)

    # ── interne ───────────────────────────────────────────────────────────────
    def _iter_raw(self):
        if not self.path.exists():
            return
        for i, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise InvalidAuditJson(f"ligne {i} : JSON invalide") from exc

    def _find_raw(self, audit_id: str):
        match = None
        for raw in self._iter_raw():
            if raw.get("audit_id") == audit_id:
                if match is not None and match.get("payload_checksum") != raw.get("payload_checksum"):
                    raise DuplicateAuditDivergent(f"doublons contradictoires : {audit_id}")
                match = raw
        return match

    def _validate(self, raw: dict) -> dict:
        for field in _REQUIRED:
            if field not in raw:
                raise AuditIncomplete(f"champ obligatoire absent : {field}")
        if raw["audit_schema_version"] != AUDIT_SCHEMA_VERSION:
            raise UnknownAuditSchemaVersion(raw["audit_schema_version"])
        if canonical.checksum(raw["payload"]) != raw["payload_checksum"]:
            raise AuditChecksumMismatch(raw["audit_id"])
        return raw
