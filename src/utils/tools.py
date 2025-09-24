# src/utils/tools_utils.py
from typing import List
from langchain_core.tools import BaseTool
from src.orchestrator.registry import build_all_tools


def get_tool_names() -> List[str]:
    """
    Return dynamically the list of all available tool names.
    Use build_all_tools() to always stay in sync with the registry.
    """
    return [tool.name for tool in build_all_tools()]


def get_tools_catalog() -> str:
    """
    Build a markdown catalog of all available tools for the LLM :
    - Tools names
    - Description (is available)
    - Arguments and their types
    """
    tools = build_all_tools()
    lines = ["## Available Tools"]

    for tool in tools:
        desc = getattr(tool, "description", "") or "No description."
        lines.append(f"\n### {tool.name}\n{desc}")
        try:
            args_schema = tool.args  
            if args_schema:
                lines.append("**Arguments :**")
                for arg, spec in args_schema.items():
                    meta = []
                    if isinstance(spec, dict):
                        if "type" in spec:
                            meta.append(f"type={spec['type']}")
                        if spec.get("default") is not None:
                            meta.append(f"default={spec['default']!r}")
                        meta_str = f" ({', '.join(meta)})" if meta else ""
                        line = f"- `{arg}`{meta_str}"
                        if spec.get("description"):
                            line += f" : {spec['description']}"
                        lines.append(line)
        except Exception:
            pass

    return "\n".join(lines)
