"""Coding specialist prompt builder — assembles base + per-stack sections dynamically."""
from __future__ import annotations

from .base import BASE_PROMPT
from .frontend import FRONTEND_PROMPT
from .python import PYTHON_PROMPT
from .rust import RUST_PROMPT
from .go import GO_PROMPT
from .node_backend import NODE_BACKEND_PROMPT
from .java import JAVA_PROMPT
from .systems import SYSTEMS_PROMPT

_STACK_PROMPTS: dict[str, str] = {
    "frontend":     FRONTEND_PROMPT,
    "node_backend": NODE_BACKEND_PROMPT,
    "python":       PYTHON_PROMPT,
    "rust":         RUST_PROMPT,
    "go":           GO_PROMPT,
    "java":         JAVA_PROMPT,
    "systems":      SYSTEMS_PROMPT,
}


def build_system_prompt(stacks: list[str]) -> str:
    """Assemble system prompt from base + up to 4 detected stack sections."""
    sections = [BASE_PROMPT]
    for stack in stacks:
        section = _STACK_PROMPTS.get(stack)
        if section:
            sections.append(section)
    return "\n\n".join(sections)
