# src/agents/gmail/tools.py
from langchain_core.tools import BaseTool
from typing import Any, List
from src.infra.mcp_gmail import ensure_session_sync, call_tool_async

class GmailMCPTool(BaseTool):
    name: str
    description: str
    mcp_tool_name: str

    def _run(self, **kwargs: Any) -> str:
        ensure_session_sync()
        result = ensure_session_sync().call_tool(self.mcp_tool_name, kwargs)
        parts: List[str] = []
        for c in (result.content or []):
            val = getattr(c, "text", None) or getattr(c, "data", None)
            if val:
                parts.append(str(val))
        return "\n".join(parts) if parts else "OK"

    async def _arun(self, **kwargs: Any) -> str:
        result = await call_tool_async(self.mcp_tool_name, kwargs)
        parts: List[str] = []
        for c in (result.content or []):
            val = getattr(c, "text", None) or getattr(c, "data", None)
            if val:
                parts.append(str(val))
        return "\n".join(parts) if parts else "OK"

def make_gmail_tools():
    return [
        GmailMCPTool(
            name="gmail_search",
            description="Recherche d'emails. Paramètres: query (str).",
            mcp_tool_name="search_emails",
        ),
        GmailMCPTool(
            name="gmail_read",
            description="Lecture d'un email par id. Paramètres: id (str).",
            mcp_tool_name="read_email",
        ),
        GmailMCPTool(
            name="gmail_send_email",
            description="Envoi d'email. Paramètres: to, subject, body, cc?, bcc?",
            mcp_tool_name="send_email",
        ),
    ]
