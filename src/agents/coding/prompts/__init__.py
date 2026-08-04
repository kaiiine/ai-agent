"""Coding specialist prompt builder — assembles base + per-stack sections dynamically."""
from __future__ import annotations

from .base import BASE_PROMPT
from .frontend import FRONTEND_PROMPT
from .nextjs import NEXTJS_PROMPT
from .angular import ANGULAR_PROMPT
from .vue import VUE_PROMPT
from .svelte import SVELTE_PROMPT
from .threedee import THREEDEE_PROMPT
from .python import PYTHON_PROMPT
from .rust import RUST_PROMPT
from .go import GO_PROMPT
from .node_backend import NODE_BACKEND_PROMPT
from .java import JAVA_PROMPT
from .systems import SYSTEMS_PROMPT

_STACK_PROMPTS: dict[str, str] = {
    # Generic frontend design rules (always added when any frontend sub-framework is detected)
    "frontend":     FRONTEND_PROMPT,
    # Framework-specific scaffold + conventions
    "nextjs":       NEXTJS_PROMPT,
    "angular":      ANGULAR_PROMPT,
    "vue":          VUE_PROMPT,
    "svelte":       SVELTE_PROMPT,
    "threedee":     THREEDEE_PROMPT,
    # Backend stacks
    "node_backend": NODE_BACKEND_PROMPT,
    "python":       PYTHON_PROMPT,
    "rust":         RUST_PROMPT,
    "go":           GO_PROMPT,
    "java":         JAVA_PROMPT,
    "systems":      SYSTEMS_PROMPT,
}

# Sub-frameworks that imply "frontend" — auto-inject the design prompt when detected
_FRONTEND_SUB_FRAMEWORKS = frozenset({"nextjs", "angular", "vue", "svelte", "threedee"})


def build_system_prompt(stacks: list[str]) -> str:
    """Assemble system prompt: base + frontend design rules (if any frontend) + framework specifics."""
    has_frontend_sub = any(s in _FRONTEND_SUB_FRAMEWORKS for s in stacks)

    sections = [BASE_PROMPT]

    # Always inject generic frontend design rules when a frontend sub-framework is present
    if has_frontend_sub and "frontend" not in stacks:
        sections.append(FRONTEND_PROMPT)

    for stack in stacks:
        try:
            from src.skills import get_skill
            section = get_skill(stack)
            if section and not section.startswith("Skill '"):
                sections.append(section)
                continue
        except Exception:
            pass
        section = _STACK_PROMPTS.get(stack)
        if section:
            sections.append(section)

    return "\n\n".join(sections)
