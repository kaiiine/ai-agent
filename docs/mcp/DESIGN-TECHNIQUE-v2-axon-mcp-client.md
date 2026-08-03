# Design Technique v2 — Axon MCP Client

Document compagnon du **PRD v2** `axon-mcp-client`. Interfaces Python suffisamment précises pour être implémentées fichier par fichier (par Axon lui-même, Claude Code ou à la main).

Codebase : `/home/kaine/Documents/projets-perso/ai-agent/`

---

## 1. Principe fondateur

Le SDK Python MCP officiel fournit déjà `stdio_client`, `ClientSession`, `initialize()`, `list_tools()`, `call_tool()` et `send_ping()`. **`MCPConnection` est une couche de lifecycle et d'adaptation autour du SDK, pas une implémentation JSON-RPC maison.**

Séparation des responsabilités :

```
Connection  → protocole / runtime d'un serveur
Manager     → orchestration de N connexions, seule source de vérité runtime
Registry    → synchronisation avec le tool registry Axon / Chroma
Adapter     → traduction des modèles MCP ↔ Axon
Commands    → surface CLI /mcp
```

## 2. Arborescence

```
axon/
└── mcp/
    ├── __init__.py
    ├── models.py       # MCPServerConfig, MCPServerRuntime, MCPToolRef, ToolResult
    ├── config.py       # load_config, save_config, resolve_env
    ├── connection.py   # MCPConnection
    ├── manager.py      # MCPClientManager
    ├── adapter.py      # adapt_schema, normalize_result, build_retrieval_text
    ├── registry.py     # register/unregister/diff_server_tools
    └── commands.py     # dispatcher /mcp
```

---

## 3. `models.py`

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Any


class MCPServerState(Enum):
    DISABLED = "disabled"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    DEGRADED = "degraded"      # process vivant, tools connus, backend instable
    ERROR = "error"


RiskLevel = Literal["read", "write", "execute", "destructive"]


@dataclass
class MCPTimeouts:
    connect_s: float = 15.0
    list_tools_s: float = 15.0
    call_s: float = 90.0


@dataclass
class MCPReconnectPolicy:
    max_retries: int = 5
    backoff_s: float = 2.0
    backoff_factor: float = 2.0


@dataclass
class MCPServerConfig:
    name: str
    transport: Literal["stdio"] = "stdio"     # v1 : stdio uniquement
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)   # valeurs "${VAR}" autorisées
    enabled: bool = True
    timeouts: MCPTimeouts = field(default_factory=MCPTimeouts)
    tool_timeouts: dict[str, float] = field(default_factory=dict)
    reconnect: MCPReconnectPolicy = field(default_factory=MCPReconnectPolicy)
    capabilities_hint: str = ""               # enrichit le document de retrieval
    risk_overrides: dict[str, RiskLevel] = field(default_factory=dict)


@dataclass
class MCPServerRuntime:
    state: MCPServerState = MCPServerState.DISCONNECTED
    last_error: str | None = None
    last_connected_at: datetime | None = None
    tool_count: int = 0
    reconnect_attempts: int = 0
    resolved_command: str | None = None       # chemin absolu réellement utilisé
    protocol_version: str | None = None
    pid: int | None = None


@dataclass
class MCPToolRef:
    """Référence STABLE. Ne contient jamais de session ni de connexion."""
    server: str
    remote_name: str                 # nom côté serveur MCP
    public_name: str                 # "blender.execute_blender_code"
    description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel = "write"
    retrieval_text: str = ""         # document indexé dans Chroma


@dataclass
class ImageArtifact:
    data: bytes | str                # base64 ou bytes
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
    Ne JAMAIS aplatir un CallToolResult en str à la source."""
    text: str | None = None
    structured: dict | list | None = None
    images: list[ImageArtifact] = field(default_factory=list)
    resources: list[ResourceRef] = field(default_factory=list)
    is_error: bool = False
    metadata: dict = field(default_factory=dict)
```

---

## 4. `config.py`

```python
import os, json, re
from pathlib import Path

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_config(path: Path) -> dict[str, MCPServerConfig]:
    """Parse .axon/mcp_servers.json -> dict[name, MCPServerConfig]."""


def save_config(path: Path, servers: dict[str, MCPServerConfig]) -> None:
    """Écriture atomique (tmp + rename) pour éviter la corruption."""


def resolve_env(env: dict[str, str]) -> dict[str, str]:
    """Résout "${GITHUB_TOKEN}" depuis os.environ.
    Lève une erreur explicite si une variable référencée est absente,
    plutôt que de lancer le serveur avec un secret vide."""
    out = {}
    for k, v in env.items():
        def _sub(m):
            name = m.group(1)
            if name not in os.environ:
                raise KeyError(f"Variable d'environnement manquante: {name} (requise par {k})")
            return os.environ[name]
        out[k] = _VAR_PATTERN.sub(_sub, v)
    return out


def build_subprocess_env(cfg: MCPServerConfig) -> dict[str, str]:
    """IMPORTANT: merge avec os.environ. Un env vide priverait le
    sous-processus de son PATH, HOME, etc."""
    return {**os.environ, **resolve_env(cfg.env)}


def resolve_command(command: str) -> str | None:
    """shutil.which(command) — le chemin résolu est affiché par /mcp test."""
    import shutil
    return shutil.which(command)
```

> `.axon/mcp_servers.json` doit figurer dans `.gitignore`, même avec l'interpolation `${VAR}`.

---

## 5. `connection.py` — `MCPConnection`

```python
import asyncio
from contextlib import AsyncExitStack


class MCPConnection:
    """Une connexion stdio à un serveur MCP. Enveloppe le SDK officiel."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.runtime = MCPServerRuntime()
        self._session = None                     # mcp.ClientSession
        self._exit_stack: AsyncExitStack | None = None
        self._connect_lock = asyncio.Lock()      # OBLIGATOIRE (cf. §5.2)
        self._tools: list[MCPToolRef] = []

    # ---------- lifecycle ----------

    async def open(self) -> None:
        """resolve_command -> StdioServerParameters -> stdio_client
        -> ClientSession -> initialize() (sous timeouts.connect_s).
        Met à jour runtime.state, resolved_command, protocol_version, pid."""

    async def close(self) -> None:
        """Ferme la session et l'exit stack, termine le sous-processus,
        remet state=DISCONNECTED. Idempotent."""

    async def restart(self) -> None:
        """Atomique. C'est la SEULE façon correcte de 'reconnecter' en stdio."""
        await self.close()
        await self.open()

    async def ensure_connected(self) -> None:
        """Point d'entrée de toute opération. Le lock empêche N tools
        échouant simultanément de déclencher N redémarrages concurrents."""
        async with self._connect_lock:
            if self.is_healthy:
                return
            await self._reconnect_with_backoff()

    async def _reconnect_with_backoff(self) -> None:
        delay = self.config.reconnect.backoff_s
        for attempt in range(1, self.config.reconnect.max_retries + 1):
            self.runtime.reconnect_attempts = attempt
            try:
                await self.restart()
                return
            except Exception as e:
                self.runtime.last_error = str(e)
                await asyncio.sleep(delay)
                delay *= self.config.reconnect.backoff_factor
        self.runtime.state = MCPServerState.ERROR

    # ---------- opérations ----------

    async def list_tools(self) -> list[MCPToolRef]:
        """session.list_tools() sous timeouts.list_tools_s,
        puis adapter.adapt_schema() pour chaque tool."""

    async def ping(self) -> bool:
        """session.send_ping(). Prouve que le process MCP répond —
        PAS que son backend (Blender) est opérationnel."""

    async def call_tool(self, remote_name: str, arguments: dict) -> ToolResult:
        """ensure_connected() -> session.call_tool() sous
        tool_timeouts.get(remote_name, timeouts.call_s)
        -> adapter.normalize_result().
        Toute exception est convertie en ToolResult(is_error=True),
        jamais propagée jusqu'à LangGraph."""

    @property
    def is_healthy(self) -> bool:
        return self.runtime.state in (MCPServerState.READY, MCPServerState.DEGRADED)
```

### 5.1 Séquence d'un `restart()`

```
close()                            open()
  ├─ session.__aexit__               ├─ resolve_command()
  ├─ exit_stack.aclose()             ├─ StdioServerParameters(cmd, args, env)
  ├─ kill subprocess si vivant       ├─ stdio_client() -> (read, write)
  └─ state = DISCONNECTED            ├─ ClientSession(read, write)
                                     ├─ initialize()          [connect_s]
                                     ├─ ping()
                                     └─ state = READY
```

### 5.2 Pourquoi le lock est non négociable

Sans lock, ce scénario est garanti dès que Blender se ferme :

```
t0  tool A échoue → reconnect
t0  tool B échoue → reconnect      →  3 subprocess uvx concurrents
t0  tool C échoue → reconnect          état incohérent, PID orphelins
```

### 5.3 Détection de `DEGRADED`

Heuristique v1 : compteur d'échecs consécutifs sur `call_tool` alors que `ping()` réussit toujours.

```
ping OK + N échecs call_tool consécutifs (N=3)  →  DEGRADED
ping KO                                          →  ERROR
call_tool OK                                     →  reset compteur, READY
```

C'est exactement le cas Blender : le serveur MCP répond, ses 20+ tools sont listés, mais la socket TCP vers l'addon Blender est cassée.

---

## 6. `manager.py` — `MCPClientManager`

**Seule source de vérité du runtime MCP.** Tout appel de tool passe par lui.

```python
class MCPClientManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.servers: dict[str, MCPServerConfig] = {}
        self.connections: dict[str, MCPConnection] = {}

    # ---------- lifecycle global ----------

    async def start(self) -> None:
        """Charge la config et connecte tous les serveurs enabled.
        asyncio.gather(..., return_exceptions=True) : un serveur down
        (Blender fermé) ne bloque JAMAIS le démarrage d'Axon."""

    async def stop(self) -> None:
        """Ferme proprement toutes les connexions."""

    # ---------- gestion par serveur ----------

    async def enable(self, name: str) -> MCPServerRuntime: ...
    async def disable(self, name: str) -> None: ...
    async def restart(self, name: str) -> MCPServerRuntime: ...
    async def refresh(self, name: str) -> "ToolDiff":
        """Re-list_tools SANS redémarrer le process. Retourne le diff
        (added / removed / changed) pour resync de l'index."""

    async def add_server(self, cfg: MCPServerConfig) -> None: ...
    async def remove_server(self, name: str) -> None: ...

    # ---------- exécution ----------

    async def call_tool(self, server: str, tool: str, arguments: dict) -> ToolResult:
        """LE point d'entrée unique d'exécution. Résout la connexion
        ACTUELLE au moment de l'appel — jamais une session capturée
        au moment de l'indexation."""
        conn = self.connections.get(server)
        if conn is None:
            return ToolResult(is_error=True, text=f"Serveur MCP inconnu: {server}")
        result = await conn.call_tool(tool, arguments)
        self._log_invocation(server, tool, result)   # provenance
        return result

    # ---------- introspection ----------

    def status(self) -> dict[str, MCPServerRuntime]: ...
    async def list_tools(self, name: str) -> list[MCPToolRef]: ...
    async def diagnose(self, name: str, deep: bool = False) -> "DiagnosticReport": ...
```

### 6.1 Log de provenance

```python
def _log_invocation(self, server, tool, result, duration_ms, risk):
    logger.info("mcp_tool_invocation", extra={
        "tool": f"{server}.{tool}",
        "source": "mcp",
        "server": server,
        "remote_tool": tool,
        "request_id": current_request_id(),
        "duration_ms": duration_ms,
        "success": not result.is_error,
        "risk_level": risk,
    })
```

---

## 7. `adapter.py`

```python
def adapt_schema(server: str, mcp_tool, cfg: MCPServerConfig) -> MCPToolRef:
    """MCP Tool -> MCPToolRef. Préfixe le nom, infère le risk_level,
    construit le retrieval_text."""
    public = f"{server}.{mcp_tool.name}"
    return MCPToolRef(
        server=server,
        remote_name=mcp_tool.name,
        public_name=public,
        description=mcp_tool.description or "",
        input_schema=mcp_tool.inputSchema,
        risk_level=cfg.risk_overrides.get(mcp_tool.name) or infer_risk(mcp_tool.name),
        retrieval_text=build_retrieval_text(server, mcp_tool, cfg),
    )


def infer_risk(name: str) -> RiskLevel:
    n = name.lower()
    if any(n.startswith(p) for p in ("delete_", "drop_", "remove_", "destroy_")):
        return "destructive"
    if any(k in n for k in ("execute", "run_", "eval", "shell", "command")):
        return "execute"
    if any(n.startswith(p) for p in ("get_", "list_", "read_", "inspect_", "search_")):
        return "read"
    return "write"          # défaut prudent pour tout MCP inconnu


def build_retrieval_text(server: str, mcp_tool, cfg: MCPServerConfig) -> str:
    """La description brute ne suffit pas : 'Execute Python code inside
    Blender' matche mal 'fais-moi un logo 3D depuis ce PNG'."""
    return "\n".join([
        f"Server: {server}",
        f"Tool: {mcp_tool.name}",
        f"Description: {mcp_tool.description or ''}",
        f"Capabilities: {cfg.capabilities_hint}",
        f"Input: {summarize_schema(mcp_tool.inputSchema)}",
    ])


def summarize_schema(schema: dict) -> str:
    """'code: string, object_name: string, location: array' — le schéma
    porte lui-même de l'information sémantique exploitable."""


def normalize_result(call_result) -> ToolResult:
    """CallToolResult -> ToolResult. Parcourt TOUS les blocs de contenu
    et les range par type (text / image / resource / structured).
    Ne concatène pas tout en une seule string."""
    out = ToolResult(is_error=bool(getattr(call_result, "isError", False)))
    texts = []
    for block in call_result.content:
        match getattr(block, "type", None):
            case "text":     texts.append(block.text)
            case "image":    out.images.append(ImageArtifact(block.data, block.mimeType))
            case "resource": out.resources.append(ResourceRef(...))
    out.text = "\n".join(texts) if texts else None
    out.structured = getattr(call_result, "structuredContent", None)
    return out
```

---

## 8. `registry.py` — synchronisation avec Chroma

```python
async def register_server_tools(manager, server: str, tool_index) -> None:
    """Indexe les MCPToolRef d'un serveur.
    Metadata Chroma pour le routing à deux étages."""
    for ref in await manager.list_tools(server):
        tool_index.upsert(
            id=ref.public_name,
            document=ref.retrieval_text,
            metadata={
                "source": "mcp",
                "server": ref.server,
                "tool": ref.remote_name,
                "risk_level": ref.risk_level,
            },
        )
    # indexe aussi le SERVEUR lui-même, pour l'étage 1 du routing
    tool_index.upsert_server(
        id=f"server:{server}",
        document=build_server_document(server),
        metadata={"source": "mcp_server", "server": server},
    )


def unregister_server_tools(server: str, tool_index) -> None:
    tool_index.delete(where={"source": "mcp", "server": server})


def diff_server_tools(old: list[MCPToolRef], new: list[MCPToolRef]) -> ToolDiff:
    """added / removed / changed(schema ou description).
    Utilisé par /mcp refresh et /mcp restart pour un resync incrémental."""
```

### 8.1 Routing à deux étages

```python
async def route(query: str, tool_index, manager, top_servers: int = 3):
    # étage 1 : quels serveurs sont pertinents ?
    servers = tool_index.query_servers(query, n=top_servers)
    #   "crée un cube dans blender" -> blender .94 | filesystem .22 | github .10

    # étage 2 : tools filtrés sur ces serveurs uniquement
    return tool_index.query_tools(
        query,
        where={"server": {"$in": [s.name for s in servers]}},
    )
```

Structure mise en place dès la v1 même avec un seul serveur : le coût est nul et la migration ultérieure évitée.

### 8.2 Handler d'exécution — le point critique

```python
# ❌ NE PAS FAIRE — capture une session qui mourra
def make_handler(conn):
    async def handler(args):
        return await conn.call_tool(name, args)   # référence morte au 1er restart
    return handler

# ✅ FAIRE — référence stable, résolution au moment de l'appel
async def execute_mcp_tool(tool_ref: MCPToolRef, args: dict, manager) -> ToolResult:
    return await manager.call_tool(
        server=tool_ref.server,
        tool=tool_ref.remote_name,
        arguments=args,
    )
```

---

## 9. `commands.py` — dispatcher `/mcp`

S'ajoute au dispatcher de slash-commands existant (à côté de `/compact`).

```python
async def handle_mcp(args: list[str], manager, tool_index) -> str:
    match args:
        case ["list"]:
            return render_status_table(manager.status())

        case ["add", name]:
            cfg = await interactive_add_server(name)     # prompts Rich
            await manager.add_server(cfg)
            return await handle_mcp(["test", name], manager, tool_index)

        case ["remove", name]:
            unregister_server_tools(name, tool_index)
            await manager.remove_server(name)

        case ["enable", name]:
            await manager.enable(name)
            await register_server_tools(manager, name, tool_index)

        case ["disable", name]:
            await manager.disable(name)
            unregister_server_tools(name, tool_index)

        case ["test", name, *flags]:
            report = await manager.diagnose(name, deep="--deep" in flags)
            return render_diagnostic(report)

        case ["tools", name]:
            return render_tools(await manager.list_tools(name))

        case ["refresh", name]:
            diff = await manager.refresh(name)
            await resync_index(diff, name, tool_index)
            return render_diff(diff)

        case ["restart", name]:
            await manager.restart(name)
            diff = await manager.refresh(name)
            await resync_index(diff, name, tool_index)
            return render_diff(diff)
```

### 9.1 `diagnose()` — étapes

```python
@dataclass
class DiagnosticStep:
    label: str
    ok: bool | None          # None = non déterminable
    detail: str
    duration_ms: float | None


async def diagnose(name, deep=False) -> DiagnosticReport:
    steps = [
        step("command resolved", resolve_command(cfg.command)),   # chemin absolu
        step("subprocess started", pid),
        step("MCP initialize", ...),
        step("protocol version", ...),
        step("tools/list", f"{n} tools"),
        step("ping", ...),
    ]
    if deep:
        steps.append(await probe_readonly_tool(name))   # opt-in, side-effect free
    else:
        steps.append(DiagnosticStep("backend health", None,
                                    "non exposé explicitement par ce serveur", None))
    return DiagnosticReport(steps)
```

`--deep` sélectionne un tool `risk_level == "read"` du serveur (ex. inspection de scène pour Blender) et l'invoque. Jamais automatique, car `tools/call` peut avoir des effets de bord.

---

## 10. Cas Blender MCP — spécificités

Référence : [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp).

### 10.1 Chaîne complète

```
Axon
  ↓ stdio MCP (JSON-RPC)
blender-mcp (uvx, sous-processus)
  ↓ socket TCP (localhost:9876 par défaut)
addon Blender (addon.py)
  ↓ bpy
scène Blender
```

Chaque maillon peut casser indépendamment — d'où l'état `DEGRADED` et le diagnostic multi-étapes.

### 10.2 Config recommandée

```json
"blender": {
  "transport": "stdio",
  "command": "uvx",
  "args": ["--python", "3.11", "blender-mcp"],
  "env": {
    "BLENDER_HOST": "localhost",
    "BLENDER_PORT": "9876",
    "DISABLE_TELEMETRY": "true",
    "UV_PYTHON_PREFERENCE": "only-managed"
  },
  "enabled": true,
  "timeouts": { "connect_s": 15, "list_tools_s": 15, "call_s": 90 },
  "tool_timeouts": { "execute_blender_code": 180 },
  "capabilities_hint": "Blender, 3D modeling, mesh manipulation, materials, geometry, animation, camera, lighting, rendering, scene editing, GLB export, Python bpy",
  "risk_overrides": { "execute_blender_code": "execute" }
}
```

Justifications :
- `BLENDER_HOST` / `BLENDER_PORT` sont les variables documentées par le README (défauts `localhost` / `9876`).
- `DISABLE_TELEMETRY=true` : le README documente une télémétrie anonyme désactivable par cette variable.
- `--python 3.11` + `UV_PYTHON_PREFERENCE=only-managed` : le README recommande explicitement ce pin pour éviter que uv ne sélectionne un interpréteur conda/pyenv/asdf incompatible.
- Installation d'uv par **l'installeur officiel** (`curl -LsSf https://astral.sh/uv/install.sh | sh` sous Linux), pas par `pip install uv` — le README indique que cette dernière méthode peut ne pas créer la commande `uvx` ou la cacher dans un environnement invisible depuis le client.

### 10.3 Fallback si `uvx` reste introuvable

```json
"command": "/home/kaine/.local/bin/uvx"
```

C'est précisément le cas que `/mcp test` doit rendre visible via la ligne `command resolved`.

### 10.4 Screenshot feedback loop

Le serveur expose la capture de screenshots de viewport. Combiné aux `ToolResult.images` (§3) et à un backend vision d'Axon :

```
prompt utilisateur
   ↓
blender.execute_blender_code  (crée / modifie)
   ↓
blender.get_viewport_screenshot  →  ToolResult.images
   ↓
backend vision Axon inspecte l'image
   ↓
correction → nouvel appel → nouveau screenshot
```

C'est la capacité la plus différenciante de l'intégration, davantage que l'export `.glb`.

### 10.5 Read-before-write appliqué à Blender

```python
SYSTEM_RULE = """
Avant toute modification d'une scène Blender existante, appelle d'abord
le tool d'inspection de scène pour récupérer les noms réels des objets
et matériaux. Ne devine jamais un nom d'objet à partir de l'historique
de conversation.
"""
```

---

## 11. Dette technique assumée en v1

| Point | Raison | Échéance |
|---|---|---|
| stdio uniquement | Couvre Blender et la majorité des serveurs communautaires | v2 : SSE/HTTP |
| `tools/list_changed` non écouté | `refresh()`/`restart()` couvrent le besoin manuellement | v2 |
| Pas de sandbox système | Politique de risque + confirmation à la place | v2+ |
| Heuristique `DEGRADED` basique | Aucun standard MCP de health backend | à affiner avec l'usage |
| Confirmation utilisateur désactivable en dev | Ergonomie pendant le développement | activer par défaut en usage courant |
