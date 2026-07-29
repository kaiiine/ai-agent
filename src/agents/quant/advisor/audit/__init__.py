"""Audit persistant & replay exact (Lot 10). Artefact PARALLÈLE à
`RecommendationResponse` (jamais dedans). Store JSONL append-only, enveloppe
versionnée à checksum, snapshots complets de config pour un replay autonome, et
replay exact offline à partir des seuls inputs archivés."""

from .config import AuditConfig, load_audit_config
from .record import build_envelope
from .replay import ReplayResult, replay_exact
from .snapshots import build_config_snapshots
from .store import JsonlAuditStore

__all__ = [
    "build_envelope", "build_config_snapshots", "JsonlAuditStore",
    "replay_exact", "ReplayResult", "AuditConfig", "load_audit_config",
]
