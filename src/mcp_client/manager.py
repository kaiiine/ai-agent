"""`MCPClientManager` — seule source de vérité du runtime MCP (DESIGN §6, §9.1).

Invariant central du PRD : **aucun tool indexé ne détient de connexion**. Un tool
détient un `MCPToolRef` (données stables) et l'exécution passe systématiquement
par `call_tool(server, tool, arguments)`, qui résout la connexion COURANTE au
moment de l'appel. Les connexions vont tomber, redémarrer, être désactivées puis
réactivées : une session capturée à l'indexation devient une référence morte à la
première coupure.

Provenance : chaque invocation est loguée avec `success = not result.failed`.
C'est le correctif clé de l'addendum — se fier à `isError` ferait mentir le log
sur tout serveur qui renvoie ses échecs backend avec `isError=False`.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from src.mcp_client.adapter import derive_probe_arguments
from src.mcp_client.config import load_config, resolve_command, save_config
from src.mcp_client.connection import MCPConnection
from src.mcp_client.models import (
    DiagnosticReport,
    DiagnosticStep,
    MCPServerConfig,
    MCPServerRuntime,
    MCPServerState,
    MCPToolRef,
    ToolDiff,
    ToolResult,
)

logger = logging.getLogger("axon.mcp")


def diff_server_tools(old: list[MCPToolRef], new: list[MCPToolRef]) -> ToolDiff:
    """`added` / `removed` / `changed` (schéma ou description). Base du resync
    incrémental de l'index côté Phase 2."""
    old_by_name = {ref.remote_name: ref for ref in old}
    new_by_name = {ref.remote_name: ref for ref in new}
    diff = ToolDiff(
        added=[new_by_name[n] for n in new_by_name if n not in old_by_name],
        removed=[old_by_name[n] for n in old_by_name if n not in new_by_name],
    )
    for name, ref in new_by_name.items():
        previous = old_by_name.get(name)
        if previous is not None and (
            previous.input_schema != ref.input_schema or previous.description != ref.description
        ):
            diff.changed.append(ref)
    return diff


class MCPClientManager:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.servers: dict[str, MCPServerConfig] = {}
        self.connections: dict[str, MCPConnection] = {}

    # ---------- lifecycle global ----------

    async def start(self) -> None:
        """Charge la config et connecte tous les serveurs activés. Un serveur down
        ne bloque JAMAIS le démarrage d'Axon : les erreurs sont absorbées dans le
        runtime du serveur concerné, les autres tools restent disponibles."""
        self.servers = load_config(self.config_path)
        self.connections = {name: MCPConnection(cfg) for name, cfg in self.servers.items()}
        await asyncio.gather(
            *(self._connect(name) for name, cfg in self.servers.items() if cfg.enabled),
            return_exceptions=True,
        )

    async def stop(self) -> None:
        await asyncio.gather(
            *(conn.close() for conn in self.connections.values()), return_exceptions=True
        )

    async def _connect(self, name: str) -> None:
        """Ouvre + découvre. Les échecs restent lisibles dans `runtime.last_error`."""
        conn = self.connections[name]
        try:
            await conn.open()
            await conn.list_tools()
        except Exception as exc:
            conn.runtime.state = MCPServerState.ERROR
            conn.runtime.last_error = str(exc)
            logger.warning("mcp_server_unavailable", extra={"server": name, "error": str(exc)})

    # ---------- gestion par serveur ----------

    def _require(self, name: str) -> MCPConnection:
        conn = self.connections.get(name)
        if conn is None:
            raise KeyError(f"Serveur MCP inconnu: {name}")
        return conn

    async def enable(self, name: str) -> MCPServerRuntime:
        conn = self._require(name)
        conn.config.enabled = True
        if conn.runtime.state is MCPServerState.DISABLED:
            conn.runtime.state = MCPServerState.DISCONNECTED
        self._persist()
        await self._connect(name)
        return conn.runtime

    async def disable(self, name: str) -> None:
        conn = self._require(name)
        await conn.close()
        conn.config.enabled = False
        conn.runtime.state = MCPServerState.DISABLED
        conn.runtime.tool_count = 0
        self._persist()

    async def restart(self, name: str) -> MCPServerRuntime:
        conn = self._require(name)
        await conn.restart()
        await conn.list_tools()
        return conn.runtime

    async def refresh(self, name: str) -> ToolDiff:
        """Re-`tools/list` SANS redémarrer le process."""
        conn = self._require(name)
        before = conn.tools
        after = await conn.list_tools()
        return diff_server_tools(before, after)

    async def add_server(self, cfg: MCPServerConfig) -> None:
        self.servers[cfg.name] = cfg
        self.connections[cfg.name] = MCPConnection(cfg)
        self._persist()
        if cfg.enabled:
            await self._connect(cfg.name)

    async def remove_server(self, name: str) -> None:
        conn = self.connections.pop(name, None)
        if conn is not None:
            await conn.close()
        self.servers.pop(name, None)
        self._persist()

    def _persist(self) -> None:
        save_config(self.config_path, self.servers)

    # ---------- exécution ----------

    async def call_tool(self, server: str, tool: str, arguments: dict) -> ToolResult:
        """LE point d'entrée unique d'exécution."""
        conn = self.connections.get(server)
        if conn is None:
            return ToolResult(
                text=f"Serveur MCP inconnu: {server}", is_error=True, error_source="transport"
            )
        started = time.perf_counter()
        result = await conn.call_tool(tool, arguments)
        duration_ms = (time.perf_counter() - started) * 1000
        risk = next(
            (ref.risk_level for ref in conn.tools if ref.remote_name == tool),
            conn.config.risk_overrides.get(tool, "write"),
        )
        self._log_invocation(server, tool, result, duration_ms, risk)
        return result

    def _log_invocation(self, server, tool, result: ToolResult, duration_ms, risk) -> None:
        logger.info(
            "mcp_tool_invocation",
            extra={
                "tool": f"{server}.{tool}",
                "source": "mcp",
                "server": server,
                "remote_tool": tool,
                "request_id": uuid.uuid4().hex,
                "duration_ms": round(duration_ms, 1),
                # `not result.is_error` mentirait sur un échec backend renvoyé
                # avec isError=False : c'est `failed` qui fait foi.
                "success": not result.failed,
                "error_source": result.error_source,
                "risk_level": risk,
            },
        )

    # ---------- introspection ----------

    def status(self) -> dict[str, MCPServerRuntime]:
        return {name: conn.runtime for name, conn in self.connections.items()}

    async def list_tools(self, name: str) -> list[MCPToolRef]:
        return await self._require(name).list_tools()

    async def diagnose(self, name: str, deep: bool = False) -> DiagnosticReport:
        """Diagnostic par étapes. Un `tools/list` réussi ne prouve pas grand-chose :
        chaque maillon de la chaîne est vérifié séparément, et le chemin résolu de
        la commande est affiché parce que le PATH d'Axon peut différer de celui du
        terminal."""
        conn = self._require(name)
        report = DiagnosticReport(server=name)

        command = resolve_command(conn.config.command)
        report.steps.append(DiagnosticStep(
            "command resolved",
            command is not None,
            command or f"introuvable dans le PATH: {conn.config.command or '(vide)'}",
        ))
        if command is None:
            return report

        started = time.perf_counter()
        try:
            await conn.restart()
        except Exception as exc:
            report.steps.append(DiagnosticStep(
                "MCP initialize", False, str(exc), (time.perf_counter() - started) * 1000
            ))
            return report

        report.steps.append(DiagnosticStep(
            # Le transport stdio du SDK n'expose pas l'objet processus : on peut
            # affirmer que le transport est ouvert, pas donner le PID.
            "subprocess started", True, "transport stdio ouvert (pid non exposé par le SDK)",
        ))
        report.steps.append(DiagnosticStep(
            "MCP initialize", True, "ok", (time.perf_counter() - started) * 1000
        ))
        report.steps.append(DiagnosticStep(
            "protocol version", True, conn.runtime.protocol_version or "inconnue"
        ))

        started = time.perf_counter()
        try:
            tools = await conn.list_tools()
            report.steps.append(DiagnosticStep(
                "tools/list", True, f"{len(tools)} tools", (time.perf_counter() - started) * 1000
            ))
        except Exception as exc:
            report.steps.append(DiagnosticStep(
                "tools/list", False, str(exc), (time.perf_counter() - started) * 1000
            ))
            tools = []

        started = time.perf_counter()
        alive = await conn.ping()
        report.steps.append(DiagnosticStep(
            "ping", alive, "ok" if alive else "sans réponse", (time.perf_counter() - started) * 1000
        ))

        report.steps.append(
            await self._probe_readonly_tool(conn, tools) if deep
            else DiagnosticStep("backend health", None, "non exposé explicitement par ce serveur")
        )
        return report

    async def _probe_readonly_tool(
        self, conn: MCPConnection, tools: list[MCPToolRef]
    ) -> DiagnosticStep:
        """`--deep` : invoque un tool d'inspection sans effet de bord. Opt-in, car
        `tools/call` peut modifier un état externe. Le tool sondé vient de
        `health.probe_tool`, à défaut du premier tool `risk_level == "read"`."""
        wanted = conn.config.health.probe_tool
        probe = next(
            (t for t in tools if t.remote_name == wanted) if wanted
            else (t for t in tools if t.risk_level == "read"),
            None,
        )
        if probe is None:
            return DiagnosticStep("backend health", None, "aucun tool read-only à sonder")

        started = time.perf_counter()
        result = await conn.call_tool(probe.remote_name, derive_probe_arguments(probe.input_schema))
        detail = (result.text or "").strip().splitlines()[0] if result.text else ""
        return DiagnosticStep(
            "backend health",
            not result.failed,
            f"{probe.remote_name}: {detail[:120]}" if result.failed else f"{probe.remote_name}: ok",
            (time.perf_counter() - started) * 1000,
        )
