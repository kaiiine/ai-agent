"""Modèles de données du client MCP (DESIGN §3, corrigé par l'ADDENDUM v2.1 §1).

Ce module ne dépend NI du SDK MCP NI du reste d'Axon : c'est la frontière interne.
Tout ce qui est spécifique à un serveur (patterns d'échec, tool de sonde, hint de
capacités) est une DONNÉE de configuration, jamais du code.

Distinction structurante, apportée par le spike de Phase 0 : un serveur peut
renvoyer un échec applicatif avec `isError=False`. `ToolResult.is_error` (protocole)
et `ToolResult.suspected_error` (prédicat de santé déclaratif) sont donc deux champs
distincts, et seul `ToolResult.failed` fait foi côté provenance et côté LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

RiskLevel = Literal["read", "write", "execute", "destructive"]
ErrorSource = Literal["protocol", "heuristic", "timeout", "transport"]


class MCPServerState(Enum):
    DISABLED = "disabled"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    DEGRADED = "degraded"  # process vivant, tools connus, backend instable
    ERROR = "error"


@dataclass
class MCPTimeouts:
    """Un timeout unique est un mauvais modèle : un handshake de 90 s est une panne,
    une opération métier de 90 s est normale."""

    connect_s: float = 15.0
    list_tools_s: float = 15.0
    call_s: float = 90.0


@dataclass
class MCPReconnectPolicy:
    max_retries: int = 5
    backoff_s: float = 2.0
    backoff_factor: float = 2.0


@dataclass
class MCPHealthPolicy:
    """Certains serveurs renvoient des échecs backend avec `isError=False`.
    Les patterns sont déclarés en CONFIG, jamais en code : c'est ce qui permet de
    détecter ces échecs sans qu'aucune connaissance d'un serveur donné n'entre
    dans `src/mcp_client/`."""

    probe_tool: str | None = None  # tool read-only pour /mcp test --deep
    failure_patterns: list[str] = field(default_factory=list)
    consecutive_failures_to_degrade: int = 3


@dataclass
class MCPServerConfig:
    name: str
    transport: Literal["stdio"] = "stdio"  # v1 : stdio uniquement
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)  # valeurs "${VAR}" autorisées
    enabled: bool = True
    timeouts: MCPTimeouts = field(default_factory=MCPTimeouts)
    tool_timeouts: dict[str, float] = field(default_factory=dict)
    reconnect: MCPReconnectPolicy = field(default_factory=MCPReconnectPolicy)
    health: MCPHealthPolicy = field(default_factory=MCPHealthPolicy)
    capabilities_hint: str = ""  # enrichit le document de retrieval
    risk_overrides: dict[str, RiskLevel] = field(default_factory=dict)


@dataclass
class MCPServerRuntime:
    state: MCPServerState = MCPServerState.DISCONNECTED
    last_error: str | None = None
    last_connected_at: datetime | None = None
    tool_count: int = 0
    reconnect_attempts: int = 0
    resolved_command: str | None = None  # chemin absolu réellement utilisé
    protocol_version: str | None = None
    pid: int | None = None  # None sur stdio : le SDK n'expose pas le sous-processus


@dataclass
class MCPToolRef:
    """Référence STABLE. Ne contient jamais de session ni de connexion : un tool
    indexé survit aux redémarrages du serveur, l'exécution résout la connexion
    courante au moment de l'appel."""

    server: str
    remote_name: str  # nom côté serveur MCP
    public_name: str  # "<serveur>.<tool>"
    description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel = "write"
    retrieval_text: str = ""  # document indexé côté retrieval


@dataclass
class ImageArtifact:
    data: bytes | str  # base64 ou bytes
    mime_type: str
    source_tool: str | None = None


@dataclass
class ResourceRef:
    uri: str
    mime_type: str | None = None
    text: str | None = None


@dataclass
class ToolResult:
    """Format interne Axon, volontairement multimodal.
    Ne JAMAIS aplatir un `CallToolResult` en `str` à la source."""

    text: str | None = None
    structured: dict | list | None = None
    images: list[ImageArtifact] = field(default_factory=list)
    resources: list[ResourceRef] = field(default_factory=list)
    is_error: bool = False  # isError du protocole MCP
    suspected_error: bool = False  # détecté par le prédicat de santé
    error_source: ErrorSource | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        """Seule notion d'échec qui fasse foi. Un résultat `failed` doit être
        présenté au modèle comme une ERREUR D'OUTIL, jamais comme une donnée."""
        return self.is_error or self.suspected_error


@dataclass
class ToolDiff:
    """Résultat d'un re-`tools/list`, consommé par le resync d'index (Phase 2)."""

    added: list[MCPToolRef] = field(default_factory=list)
    removed: list[MCPToolRef] = field(default_factory=list)
    changed: list[MCPToolRef] = field(default_factory=list)  # version NOUVELLE

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


@dataclass
class DiagnosticStep:
    label: str
    ok: bool | None  # None = non déterminable
    detail: str
    duration_ms: float | None = None


@dataclass
class DiagnosticReport:
    server: str
    steps: list[DiagnosticStep] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Une étape non déterminable (`ok is None`) ne fait pas échouer le rapport."""
        return all(s.ok is not False for s in self.steps)
