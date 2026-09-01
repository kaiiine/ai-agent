"""Tool `load_skill`, fabriqué par contexte — seule la portée sépare les agents."""
from __future__ import annotations

from langchain_core.tools import StructuredTool

_TEMPLATE = """\
Loads the guidelines WRITTEN FOR THIS PROJECT about a domain.

Call this FIRST — before any other tool — whenever the request touches one of the
skills below. This is not an optimisation you may skip when the task looks simple:
these guidelines exist because the default approach already failed on this domain.
Checking the list is unconditional; only the loading depends on a match.

Skills COMPOSE — call this tool once per skill that applies, not once total.
A stack skill says WHAT to install and scaffold; a cross-cutting skill says HOW
the result must behave or look. They answer different questions, so loading one
never replaces the other. When a request names a stack AND a quality bar ("a
site in <framework>, with a great design"), load both.

Never name a skill here that the catalogue below does not list: this preamble is
shared by every agent, and each one sees a different catalogue.

Available skills:
{catalogue}

Args:
    stack: a skill name from the list above
Returns:
    The full guidelines text for that skill
"""


#: Combien de skills on montre quand la requête est connue. Mesuré sur vingt
#: requêtes dont on connaît la bonne réponse : le rappel est de 80 % à 3 et de
#: 95 % à 5, et il ne bouge plus au-delà. Le catalogue entier coûtait 2 241
#: tokens à chaque tour — et devant 49 entrées, le modèle n'en prenait aucune.
BUDGET_SKILLS = 5


def make_load_skill(scope: str, requete: str = "") -> StructuredTool:
    """Une fabrique et non un singleton : les deux agents tournent dans le même
    processus, un objet partagé montrerait à l'un le catalogue de l'autre.

    `requete` RESTREINT le catalogue à ce qui la concerne. Sans elle — au
    démarrage, quand aucune question n'est encore posée — on montre tout : mieux
    vaut un catalogue large qu'un catalogue deviné.
    """
    from src.skills import describe_skills, get_skill, list_skills, skills_pertinentes

    entries = describe_skills(scope)
    if requete.strip():
        retenues = set(skills_pertinentes(requete, scope, BUDGET_SKILLS))
        if retenues:
            entries = [(n, d) for n, d in entries if n in retenues]
    catalogue = "\n".join(f"  - {n}: {d}" for n, d in entries) if entries else "  (aucun)"

    def _run(stack: str) -> str:
        result = get_skill(stack, scope=scope)
        if result and not result.startswith("Skill '"):
            return result
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
