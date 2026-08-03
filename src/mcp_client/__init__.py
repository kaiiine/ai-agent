"""Client MCP d'Axon — Phase 1 (cœur, sans intégration retrieval ni CLI).

    MCPClientManager   seule source de vérité du runtime MCP
        MCPConnection  lifecycle d'UN serveur (enveloppe le SDK officiel)
            adapter    traduction modèles MCP <-> modèles Axon

Invariant : aucun tool ne détient de `ClientSession` ni de `MCPConnection`.
Toute exécution passe par `MCPClientManager.call_tool(server, tool, arguments)`,
qui résout la connexion COURANTE au moment de l'appel.
"""

from src.mcp_client.models import (  # noqa: F401
    DiagnosticReport,
    DiagnosticStep,
    ImageArtifact,
    MCPHealthPolicy,
    MCPReconnectPolicy,
    MCPServerConfig,
    MCPServerRuntime,
    MCPServerState,
    MCPTimeouts,
    MCPToolRef,
    ResourceRef,
    RiskLevel,
    ToolDiff,
    ToolResult,
)

__all__ = [
    "DiagnosticReport",
    "DiagnosticStep",
    "ImageArtifact",
    "MCPHealthPolicy",
    "MCPReconnectPolicy",
    "MCPServerConfig",
    "MCPServerRuntime",
    "MCPServerState",
    "MCPTimeouts",
    "MCPToolRef",
    "ResourceRef",
    "RiskLevel",
    "ToolDiff",
    "ToolResult",
]
