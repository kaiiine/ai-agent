"""Configuration versionnée de l'audit (Lot 10 §33). `audit_store_path` est
INJECTABLE (les tests utilisent un chemin temporaire) ; la valeur repo-local V1
vit sous `var/` (déjà gitignoré). Aucun chemin utilisateur absolu codé en dur,
et JAMAIS `~/.axon` (interdiction stable)."""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass

from .schema import AUDIT_SCHEMA_VERSION

_CONFIG_PATH = (
    pathlib.Path(__file__).resolve().parents[5]
    / "configs" / "advisor" / "audit_policy.json"
)
_CHECKSUM_FIELDS = ("config_version", "effective_from", "audit_store_path", "audit_schema_version")


@dataclass(frozen=True)
class AuditConfig:
    config_version: str
    effective_from: str
    checksum: str
    audit_store_path: str
    audit_schema_version: str


def _expected_checksum(data: dict) -> str:
    payload = {k: data[k] for k in _CHECKSUM_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_audit_config(path: pathlib.Path = _CONFIG_PATH) -> AuditConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in (*_CHECKSUM_FIELDS, "checksum"):
        if field not in data:
            raise ValueError(f"clé de configuration audit manquante : {field}")
    if data["checksum"] != _expected_checksum(data):
        raise ValueError("checksum de configuration audit invalide")
    if data["audit_schema_version"] != AUDIT_SCHEMA_VERSION:
        raise ValueError(f"audit_schema_version {data['audit_schema_version']} != {AUDIT_SCHEMA_VERSION}")
    if "~/.axon" in data["audit_store_path"] or data["audit_store_path"].startswith("~"):
        raise ValueError("audit_store_path ne doit pas cibler un dossier utilisateur / ~/.axon")
    return AuditConfig(
        config_version=data["config_version"], effective_from=data["effective_from"],
        checksum=data["checksum"], audit_store_path=data["audit_store_path"],
        audit_schema_version=data["audit_schema_version"])
