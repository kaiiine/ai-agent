"""Phase 0 — spike MCP/Blender hors Axon (TEST-PLAN §Phase 0).

Chaîne testée : uvx -> blender-mcp (stdio JSON-RPC) -> socket :9876 -> addon Blender.
Critère de sortie : un call_tool d'inspection de scène réussi, sans Axon/Chroma/LangGraph.

    python scripts/spike_mcp_blender.py
"""

import asyncio, shutil, sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

# DESIGN-TECHNIQUE §10.2 — pin 3.11 + only-managed : évite un interpréteur conda/pyenv.
ENV = {"BLENDER_HOST": "localhost", "BLENDER_PORT": "9876",
       "DISABLE_TELEMETRY": "true", "UV_PYTHON_PREFERENCE": "only-managed"}


async def main() -> int:
    command = shutil.which("uvx")
    print(f"uvx resolved       {command or '(introuvable dans le PATH)'}")
    if not command:
        return 1  # §10.3 : fallback = chemin absolu dans la config

    params = StdioServerParameters(command=command, args=["--python", "3.11", "blender-mcp"],
                                   env={**get_default_environment(), **ENV})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await asyncio.wait_for(session.initialize(), timeout=60)
        print(f"protocol version   {init.protocolVersion}")
        print(f"server             {init.serverInfo.name} {init.serverInfo.version}")

        tools = (await session.list_tools()).tools
        print(f"tools/list         {len(tools)}")
        for t in tools:
            print(f"  - {t.name}")

        tool = next(t for t in tools if "scene_info" in t.name)
        # blender-mcp 1.29 exige `user_prompt` (télémétrie) même désactivée : args dérivés du schéma.
        args = {k: "spike: inspecte la scène" for k in tool.inputSchema.get("required", [])}
        print(f"call_tool          {tool.name} {args}")
        res = await session.call_tool(tool.name, args)
        text = "\n".join(getattr(b, "text", str(b)) for b in res.content)
        print(text)
        # Piège : ce serveur renvoie ses échecs en texte avec isError=False. Le critère de
        # sortie est que l'appel ait vraiment atteint Blender, pas qu'il ait répondu.
        reached = res.isError is False and "Could not connect to Blender" not in text
        print(f"isError            {res.isError}   → atteint Blender : {reached}")
        return 0 if reached else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
