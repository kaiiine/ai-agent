"""Traduction modèles MCP <-> modèles Axon (DESIGN §7, ADDENDUM v2.1 §1 et §2).

Fonctions pures, sans I/O ni session : tout est testable sans serveur. Les objets
`mcp_tool` sont consommés en canard (`.name`, `.description`, `.inputSchema`), ce
qui évite de coupler l'adaptation aux classes du SDK.

Aucun nom de serveur, de tool ou de message d'erreur particulier n'apparaît ici :
la connaissance d'un serveur donné entre exclusivement par `MCPServerConfig`.
"""

from __future__ import annotations

from typing import Any

from src.mcp_client.models import (
    ImageArtifact,
    MCPHealthPolicy,
    MCPServerConfig,
    MCPToolRef,
    ResourceRef,
    RiskLevel,
    ToolResult,
)

_DESTRUCTIVE_PREFIXES = ("delete_", "drop_", "remove_", "destroy_")
_EXECUTE_KEYWORDS = ("execute", "run_", "eval", "shell", "command")
_READ_PREFIXES = ("get_", "list_", "read_", "inspect_", "search_")


def infer_risk(name: str) -> RiskLevel:
    """Heuristique par défaut. Le défaut d'un MCP inconnu est `write`, jamais
    `read` : sous-estimer le risque est le seul sens dans lequel l'erreur coûte."""
    n = name.lower()
    if any(n.startswith(p) for p in _DESTRUCTIVE_PREFIXES):
        return "destructive"
    if any(k in n for k in _EXECUTE_KEYWORDS):
        return "execute"
    if any(n.startswith(p) for p in _READ_PREFIXES):
        return "read"
    return "write"


def summarize_schema(schema: dict[str, Any] | None) -> str:
    """`"code: string, location: array"` — le schéma d'entrée porte lui-même de
    l'information sémantique exploitable par le retrieval."""
    props = (schema or {}).get("properties") or {}
    return ", ".join(f"{n}: {(s or {}).get('type', 'any')}" for n, s in props.items())


def build_retrieval_text(server: str, mcp_tool: Any, cfg: MCPServerConfig) -> str:
    """La description brute d'un tool matche mal une requête utilisateur formulée
    en intention métier : on indexe donc nom + description + schéma.

    NI le nom du serveur NI son `capabilities_hint` : identiques sur tous les
    documents d'un même serveur, ils ne discriminent rien à l'étage 2 et noient la
    description propre à chaque tool. L'étage 2 est de toute façon déjà filtré par
    serveur (`where`), donc les répéter est redondant. Mesuré sur un serveur de 22
    tools, rang moyen du tool d'exécution générique : 9,7 avec les deux, 2,0 sans.
    Le hint reste dans le document de serveur, où il sert l'étage 1."""
    return "\n".join([
        f"Tool: {mcp_tool.name}",
        f"Description: {getattr(mcp_tool, 'description', '') or ''}",
        f"Input: {summarize_schema(getattr(mcp_tool, 'inputSchema', None))}",
    ])


def adapt_schema(server: str, mcp_tool: Any, cfg: MCPServerConfig) -> MCPToolRef:
    """Tool MCP -> `MCPToolRef`. Préfixe le nom public, infère le risque, construit
    le document de retrieval."""
    name = mcp_tool.name
    return MCPToolRef(
        server=server,
        remote_name=name,
        public_name=f"{server}.{name}",
        description=getattr(mcp_tool, "description", "") or "",
        input_schema=getattr(mcp_tool, "inputSchema", None) or {},
        risk_level=cfg.risk_overrides.get(name) or infer_risk(name),
        retrieval_text=build_retrieval_text(server, mcp_tool, cfg),
    )


def normalize_result(call_result: Any, *, source_tool: str | None = None) -> ToolResult:
    """`CallToolResult` -> `ToolResult`. Parcourt TOUS les blocs et les range par
    type. N'aplatit jamais l'ensemble en une seule string : une image concaténée
    dans du texte est une image perdue, et l'échec est alors silencieux."""
    out = ToolResult(is_error=bool(getattr(call_result, "isError", False)))
    texts: list[str] = []
    unhandled: set[str] = set()

    for block in getattr(call_result, "content", None) or []:
        kind = getattr(block, "type", None)
        match kind:
            case "text":
                texts.append(block.text)
            case "image":
                out.images.append(
                    ImageArtifact(data=block.data, mime_type=block.mimeType, source_tool=source_tool)
                )
            case "resource":
                res = block.resource
                out.resources.append(ResourceRef(
                    uri=str(getattr(res, "uri", "")),
                    mime_type=getattr(res, "mimeType", None),
                    text=getattr(res, "text", None),
                ))
            case "resource_link":
                out.resources.append(ResourceRef(
                    uri=str(getattr(block, "uri", "")),
                    mime_type=getattr(block, "mimeType", None),
                ))
            case _:
                # Jamais silencieux : un type de bloc non géré est tracé, pas jeté.
                unhandled.add(str(kind))

    out.text = "\n".join(texts) if texts else None
    out.structured = getattr(call_result, "structuredContent", None)
    if unhandled:
        out.metadata["unhandled_block_types"] = sorted(unhandled)
    if out.is_error:
        out.error_source = "protocol"
    return out


def apply_health_policy(result: ToolResult, policy: MCPHealthPolicy) -> ToolResult:
    """Prédicat de santé DÉCLARATIF : les patterns viennent de la config du serveur.

    Motif — le protocole ne suffit pas. Un serveur dont le backend est injoignable
    peut répondre `isError=False` avec son message d'erreur en guise de contenu.
    Sans ce prédicat, la provenance logue un succès et le modèle raisonne sur le
    message d'erreur comme s'il s'agissait d'une donnée métier."""
    if result.is_error:
        result.error_source = "protocol"
        return result
    if result.text and policy.failure_patterns:
        haystack = result.text.lower()
        if any(p.lower() in haystack for p in policy.failure_patterns):
            result.suspected_error = True
            result.error_source = "heuristic"
    return result


def derive_probe_arguments(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Remplit les champs REQUIRED d'un `inputSchema` avec des valeurs bénignes
    typées. Générique : aucun nom de champ en dur.

    Motif — appeler un tool de sonde avec `{}` échoue dès qu'un serveur exige un
    paramètre inattendu (le spike l'a rencontré sur un champ requis pour de la
    télémétrie, même télémétrie désactivée)."""
    schema = schema or {}
    props = schema.get("properties") or {}
    args: dict[str, Any] = {}
    for name in schema.get("required", []):
        spec = props.get(name) or {}
        if "default" in spec:
            args[name] = spec["default"]
            continue
        if spec.get("enum"):
            args[name] = spec["enum"][0]
            continue
        match spec.get("type"):
            case "string":
                args[name] = "axon health probe"
            case "integer" | "number":
                args[name] = 0
            case "boolean":
                args[name] = False
            case "array":
                args[name] = []
            case "object":
                args[name] = {}
            case _:
                args[name] = None
    return args
