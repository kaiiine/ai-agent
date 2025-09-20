# src/infra/mcp_gmail.py
import asyncio
from typing import Optional, Dict, Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_session: Optional[ClientSession] = None

async def _open_session() -> ClientSession:
    params = StdioServerParameters(
        command="npx",
        args=["-y", "-p", "@gongrzhe/server-gmail-autoauth-mcp", "gmail-mcp"],
    )
    read, write = await stdio_client(params).__aenter__()
    session = ClientSession(read, write)
    await session.__aenter__()
    await session.initialize()
    return session

def ensure_session_sync() -> ClientSession:
    global _session
    if _session is None:
        loop = asyncio.get_event_loop()
        _session = loop.run_until_complete(_open_session())
    return _session

async def call_tool_async(tool_name: str, arguments: Dict[str, Any]):
    global _session
    if _session is None:
        _session = await _open_session()
    return await _session.call_tool(tool_name, arguments)
