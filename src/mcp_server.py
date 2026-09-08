"""
Axon MCP Server — expose tous les tools Axon via le Model Context Protocol.
Compatible : Zed, Claude Desktop, Cursor, Cline, et tout client MCP.

── Lancement ────────────────────────────────────────────────────────────────
    python src/mcp_server.py          # depuis la racine du projet, venv activé

── Zed  (~/.config/zed/settings.json) ───────────────────────────────────────
    "context_servers": {
      "axon": {
        "command": {
          "path": "/home/kaine/.venvs/axon/bin/python",
          "args": ["/home/kaine/Documents/projets-perso/ai-agent/src/mcp_server.py"]
        }
      }
    }

── Claude Desktop  (~/.config/claude/claude_desktop_config.json) ────────────
    "mcpServers": {
      "axon": {
        "command": "/home/kaine/.venvs/axon/bin/python",
        "args": ["/home/kaine/Documents/projets-perso/ai-agent/src/mcp_server.py"],
        "env": { "PYTHONPATH": "/home/kaine/Documents/projets-perso/ai-agent" }
      }
    }

── Cursor / Cline (.cursor/mcp.json ou équivalent) ──────────────────────────
    {
      "mcpServers": {
        "axon": {
          "command": "/home/kaine/.venvs/axon/bin/python",
          "args": ["/home/kaine/Documents/projets-perso/ai-agent/src/mcp_server.py"]
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Garantit que les imports src.* fonctionnent quel que soit le CWD du client MCP
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from src.infra import chemins as _chemins

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

app = Server("axon")

# Idem côté MCP : ces tours viennent d'un IDE, pas du terminal.
from src.infra import trace as _trace

_trace.declarer_source("mcp")

_tools_cache: list | None = None


def _load_tools() -> list:
    global _tools_cache
    if _tools_cache is None:
        from src.orchestrator.registry import build_all_tools
        _tools_cache = build_all_tools()
    return _tools_cache


def _schema_for(lc_tool) -> dict:
    """Extrait le JSON Schema depuis args_schema (Pydantic v1 ou v2)."""
    if not lc_tool.args_schema:
        return {"type": "object", "properties": {}}
    try:
        schema = lc_tool.args_schema.model_json_schema()   # Pydantic v2
    except AttributeError:
        try:
            schema = lc_tool.args_schema.schema()           # Pydantic v1
        except Exception:
            return {"type": "object", "properties": {}}
    schema.pop("title", None)
    return schema


def _to_mcp_tool(lc_tool) -> types.Tool:
    return types.Tool(
        name=lc_tool.name,
        description=(lc_tool.description or "").strip(),
        inputSchema=_schema_for(lc_tool),
    )


# ── Outils supplémentaires hors registry (key pool) ──────────────────────────

def _extra_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="axon_keys_status",
            description="Affiche l'état des clés API Axon (multi-comptes) : provider, clé masquée, saine/cooldown.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="axon_keys_reset",
            description="Remet toutes les clés API en état sain (utile après rotation de clés).",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "Provider à reset (ollama_cloud, gemini, mistral, groq). Vide = tout reset.",
                    }
                },
            },
        ),
    ]


async def _call_extra(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "axon_keys_status":
        from src.llm.key_pool import get_pool
        rows = get_pool().status()
        if not rows:
            return [types.TextContent(type="text", text="Aucune clé configurée.")]
        lines = ["Provider         Clé              État      Cooldown"]
        lines.append("-" * 55)
        for r in rows:
            state = "✓ saine" if r["healthy"] else "✗ cooldown"
            cd = ""
            if not r["healthy"]:
                secs = r["cooldown_left"]
                h, m = divmod(secs // 60, 60)
                cd = f"{h}h {m:02d}m" if h else f"{m}m"
            lines.append(f"{r['provider']:<16} {r['key_short']:<16} {state:<9} {cd}")
        return [types.TextContent(type="text", text="\n".join(lines))]

    if name == "axon_keys_reset":
        from src.llm.key_pool import get_pool
        pool = get_pool()
        provider = (arguments or {}).get("provider", "").strip()
        if provider:
            pool.reset_provider(provider)
            return [types.TextContent(type="text", text=f"Clés {provider} remises en état sain.")]
        pool.reset_all()
        return [types.TextContent(type="text", text="Toutes les clés remises en état sain.")]

    return [types.TextContent(type="text", text=f'Outil extra inconnu : "{name}"')]


# ── Handlers MCP ─────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    try:
        lc_tools = [_to_mcp_tool(t) for t in _load_tools()]
        return lc_tools + _extra_tools()
    except Exception as exc:
        logger.exception("list_tools failed: %s", exc)
        return _extra_tools()


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict[str, Any] | None,
) -> list[types.TextContent | types.ImageContent]:
    args = arguments or {}

    # Outils extra (key pool)
    if name.startswith("axon_keys_"):
        return await _call_extra(name, args)

    # Outils LangChain
    tool_map = {t.name: t for t in _load_tools()}
    lc_tool = tool_map.get(name)
    if lc_tool is None:
        return [types.TextContent(type="text", text=f'Outil inconnu : "{name}"')]

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: lc_tool.invoke(args))
    except Exception as exc:
        logger.exception("call_tool %s failed", name)
        return [types.TextContent(type="text", text=f"Erreur : {exc}")]

    if isinstance(result, (dict, list)):
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        text = str(result)

    return [types.TextContent(type="text", text=text)]


# ── Resources : mémoire Axon (lecture seule) ─────────────────────────────────

@app.list_resources()
async def list_resources() -> list[types.Resource]:
    resources: list[types.Resource] = []
    memory_dir = _chemins.memoire_projet()
    if memory_dir.is_dir():
        for f in sorted(memory_dir.glob("*.md")):
            resources.append(types.Resource(
                uri=f"axon://memory/{f.name}",
                name=f"Axon memory · {f.stem}",
                description=f"Note mémoire Axon : {f.name}",
                mimeType="text/markdown",
            ))
    return resources


@app.read_resource()
async def read_resource(uri: str) -> str:
    if not uri.startswith("axon://memory/"):
        raise ValueError(f"URI inconnue : {uri}")
    fname = uri.removeprefix("axon://memory/")
    path = _chemins.memoire_projet() / fname
    if not path.exists():
        raise FileNotFoundError(f"Ressource introuvable : {path}")
    return path.read_text(encoding="utf-8")


# ── Entry point ───────────────────────────────────────────────────────────────

async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_main())
