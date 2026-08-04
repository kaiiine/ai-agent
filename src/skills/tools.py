"""Tool `load_skill`, fabriqué par contexte.

Ne connaît ni l'agent coding ni l'orchestrateur : ce qui leur est propre — comme
le repli sur _STACK_PROMPTS — est injecté.
"""
from __future__ import annotations

from typing import Callable

from langchain_core.tools import StructuredTool

_TEMPLATE = """\
Loads the guidelines WRITTEN FOR THIS PROJECT about a domain.

Call this FIRST — before any other tool — whenever the request touches one of the
skills below. This is not an optimisation you may skip when the task looks simple:
these guidelines exist because the default approach already failed on this domain.
Checking the list is unconditional; only the loading depends on a match.

Available skills:
{catalogue}

Args:
    stack: a skill name from the list above
Returns:
    The full guidelines text for that skill
"""


def make_load_skill(scope: str, *, fallback: Callable[[str], str|None]|None = None) -> StructuredTool:
    """Une fabrique et non un singleton : les deux agents tournent dans le même
    processus, un objet partagé montrerait à l'un le catalogue de l'autre."""
    from src.skills import describe_skills, get_skill, list_skills

    entries = describe_skills(scope)
    catalogue = "\n".join(f"  - {n}: {d}" for n, d in entries) if entries else "  (aucun)"

    def _run(stack: str) -> str:
        result = get_skill(stack, scope=scope)
        if result and not result.startswith("Skill '"):
            return result
        if fallback is not None:
            replacement = fallback(stack)
            if replacement:
                return replacement
        return f"Skill '{stack}' non disponible ici. Disponibles : {', '.join(list_skills(scope))}"

    return StructuredTool.from_function(
        func=_run, name="load_skill", description=_TEMPLATE.format(catalogue=catalogue)
    )


def anchors_for(scope: str) -> list[str]:
    try:
        from src.skills import skill_anchors
        return skill_anchors(scope)
    except Exception:
        return []
