"""`MCPConnection` — lifecycle d'UNE connexion stdio (DESIGN §5, ADDENDUM v2.1 §1).

Couche de lifecycle autour du SDK officiel, pas une implémentation JSON-RPC maison.

Deux choix structurants :

1. **Le transport est possédé par une tâche dédiée.** `stdio_client` et
   `ClientSession` sont des context managers asynchrones bâtis sur anyio : entrer
   leur scope dans une tâche et en sortir dans une autre lève
   « attempted to exit cancel scope in a different task ». Comme un serveur va être
   ouvert par le démarrage et fermé par un `/mcp restart` ou un appel de tool, on
   confie l'`AsyncExitStack` à une tâche « porteuse » qui l'ouvre et la ferme
   elle-même ; `open()` attend qu'elle soit prête, `close()` lui demande de sortir.
   La `ClientSession` obtenue reste utilisable depuis n'importe quelle tâche.

2. **`ensure_connected()` est sérialisé par un `asyncio.Lock`.** Sans lui, trois
   tools qui échouent en même temps déclenchent trois redémarrages concurrents du
   sous-processus : PID orphelins et état incohérent garantis.

`call_tool()` ne propage JAMAIS d'exception : toute panne devient un `ToolResult`
en échec, parce qu'une exception qui remonte jusqu'au graphe tue le tour de
conversation au lieu de laisser le modèle réagir à l'erreur.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import AsyncExitStack
from datetime import datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.mcp_client.adapter import adapt_schema, apply_health_policy, normalize_result
from src.mcp_client.config import build_subprocess_env, resolve_command
from src.mcp_client.models import (
    MCPServerConfig,
    MCPServerRuntime,
    MCPServerState,
    MCPToolRef,
    ToolResult,
)

_CLOSE_TIMEOUT_S = 10.0


class MCPConnectionError(RuntimeError):
    """Échec de lifecycle (commande introuvable, handshake KO, serveur désactivé)."""


class MCPConnection:
    """Une connexion stdio à un serveur MCP."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.runtime = MCPServerRuntime(
            state=MCPServerState.DISABLED if not config.enabled else MCPServerState.DISCONNECTED
        )
        self._session: ClientSession | None = None
        self._connect_lock = asyncio.Lock()  # OBLIGATOIRE (cf. docstring)
        self._tools: list[MCPToolRef] = []
        self._carrier: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._carrier_error: BaseException | None = None
        self._consecutive_failures = 0

    # ---------- lifecycle ----------

    def _fail(self, message: str) -> None:
        self.runtime.state = MCPServerState.ERROR
        self.runtime.last_error = message

    async def _carry(self, command: str) -> None:
        """Tâche porteuse : ouvre le transport, signale `ready`, puis reste bloquée
        jusqu'à `close()`. Entrée ET sortie de l'exit stack dans la MÊME tâche."""
        try:
            params = StdioServerParameters(
                command=command,
                args=list(self.config.args),
                env=build_subprocess_env(self.config),
            )
            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                init = await session.initialize()
                self.runtime.protocol_version = str(getattr(init, "protocolVersion", "") or "")
                self._session = session
                self._ready.set()
                await self._stop.wait()
        except Exception as exc:
            self._carrier_error = exc
        finally:
            self._session = None
            self._ready.set()  # débloque `open()` même quand le démarrage échoue

    async def open(self) -> None:
        """`resolve_command` -> `stdio_client` -> `ClientSession` -> `initialize()`,
        le tout sous `timeouts.connect_s`."""
        if not self.config.enabled:
            self.runtime.state = MCPServerState.DISABLED
            raise MCPConnectionError(f"serveur '{self.config.name}' désactivé en config")
        if self._carrier is not None:
            await self.close()

        command = resolve_command(self.config.command)
        if command is None:
            self._fail(f"commande introuvable dans le PATH: {self.config.command or '(vide)'}")
            raise MCPConnectionError(self.runtime.last_error or "")
        self.runtime.resolved_command = command
        self.runtime.state = MCPServerState.CONNECTING

        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._carrier_error = None
        self._carrier = asyncio.create_task(self._carry(command), name=f"mcp:{self.config.name}")

        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self.config.timeouts.connect_s)
        except asyncio.TimeoutError:
            await self.close()
            self._fail(f"initialize: timeout après {self.config.timeouts.connect_s}s")
            raise MCPConnectionError(self.runtime.last_error or "")

        if self._carrier_error is not None or self._session is None:
            detail = str(self._carrier_error) if self._carrier_error else "session non établie"
            await self.close()
            self._fail(detail)
            raise MCPConnectionError(detail)

        self.runtime.state = MCPServerState.READY
        self.runtime.last_connected_at = datetime.now()
        self.runtime.last_error = None
        self.runtime.reconnect_attempts = 0
        self._consecutive_failures = 0

    async def close(self) -> None:
        """Ferme la session, l'exit stack et le sous-processus. Idempotent."""
        self._stop.set()
        carrier, self._carrier = self._carrier, None
        if carrier is not None:
            try:
                await asyncio.wait_for(carrier, timeout=_CLOSE_TIMEOUT_S)
            except asyncio.TimeoutError:
                # wait_for a déjà annulé la tâche ; on absorbe sa CancelledError.
                with contextlib.suppress(BaseException):
                    await carrier
            except Exception:
                pass  # l'erreur de sortie du transport ne doit pas empêcher la fermeture
        self._session = None
        if self.runtime.state is not MCPServerState.DISABLED:
            self.runtime.state = MCPServerState.DISCONNECTED

    async def restart(self) -> None:
        """Atomique. C'est la SEULE façon correcte de « reconnecter » en stdio :
        un sous-processus mort ne se rattrape pas, il se relance."""
        await self.close()
        await self.open()

    async def ensure_connected(self) -> None:
        """Point d'entrée de toute opération."""
        async with self._connect_lock:
            if self.is_healthy and self._session is not None:
                return
            await self._reconnect_with_backoff()

    async def _reconnect_with_backoff(self) -> None:
        delay = self.config.reconnect.backoff_s
        attempts = max(1, self.config.reconnect.max_retries)
        for attempt in range(1, attempts + 1):
            self.runtime.reconnect_attempts = attempt
            try:
                await self.restart()
                return
            except Exception as exc:
                self.runtime.last_error = str(exc)
                if attempt < attempts:
                    await asyncio.sleep(delay)
                    delay *= self.config.reconnect.backoff_factor
        self.runtime.state = MCPServerState.ERROR

    # ---------- opérations ----------

    async def list_tools(self) -> list[MCPToolRef]:
        await self.ensure_connected()
        if self._session is None:
            raise MCPConnectionError(self.runtime.last_error or "session non établie")
        response = await asyncio.wait_for(
            self._session.list_tools(), timeout=self.config.timeouts.list_tools_s
        )
        self._tools = [
            adapt_schema(self.config.name, tool, self.config) for tool in response.tools
        ]
        self.runtime.tool_count = len(self._tools)
        return list(self._tools)

    @property
    def tools(self) -> list[MCPToolRef]:
        """Dernier `tools/list` connu, sans I/O (base du diff de `refresh`)."""
        return list(self._tools)

    async def ping(self) -> bool:
        """Prouve que le process MCP répond — PAS que son backend est opérationnel.
        C'est précisément cette distinction qui sépare `DEGRADED` de `ERROR`."""
        if self._session is None:
            return False
        try:
            await asyncio.wait_for(
                self._session.send_ping(), timeout=self.config.timeouts.connect_s
            )
            return True
        except Exception:
            return False

    async def call_tool(self, remote_name: str, arguments: dict) -> ToolResult:
        try:
            await self.ensure_connected()
        except Exception as exc:  # ensure_connected ne doit pas fuiter non plus
            self.runtime.last_error = str(exc)
        if self._session is None:
            return ToolResult(
                text=f"serveur MCP indisponible: {self.runtime.last_error or 'non connecté'}",
                is_error=True,
                error_source="transport",
            )

        timeout = self.config.tool_timeouts.get(remote_name, self.config.timeouts.call_s)
        public_name = f"{self.config.name}.{remote_name}"
        try:
            raw = await asyncio.wait_for(
                self._session.call_tool(remote_name, arguments), timeout=timeout
            )
        except asyncio.TimeoutError:
            result = ToolResult(
                text=f"timeout après {timeout}s sur {public_name}",
                is_error=True,
                error_source="timeout",
            )
        except Exception as exc:
            result = ToolResult(text=str(exc), is_error=True, error_source="transport")
        else:
            result = apply_health_policy(
                normalize_result(raw, source_tool=public_name), self.config.health
            )

        await self._update_health(result)
        return result

    async def _update_health(self, result: ToolResult) -> None:
        """Machine à états de la santé backend (ADDENDUM §5.3 réécrit) :

            ping OK  + N résultats consécutifs `failed` -> DEGRADED
            ping KO                                     -> ERROR
            result.failed == False                      -> reset compteur, READY
        """
        if not result.failed:
            self._consecutive_failures = 0
            if self.runtime.state is MCPServerState.DEGRADED:
                self.runtime.state = MCPServerState.READY
            return

        self._consecutive_failures += 1
        self.runtime.last_error = result.text
        if self._consecutive_failures >= self.config.health.consecutive_failures_to_degrade:
            self.runtime.state = (
                MCPServerState.DEGRADED if await self.ping() else MCPServerState.ERROR
            )

    @property
    def is_healthy(self) -> bool:
        return self.runtime.state in (MCPServerState.READY, MCPServerState.DEGRADED)
