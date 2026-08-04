"""Skills projet — guides markdown chargés à la demande.

Chaque skill déclare qui peut le lire dans son frontmatter :

    scope: [coding, orchestrator]     lisible des deux
    scope: orchestrator               hors code seulement
    (absent)                          coding uniquement — défaut

Les consommateurs passent par ici, jamais par `retriever` directement.
"""
from src.skills.retriever import (
    describe_skills,
    get_skill,
    list_skills,
    scopes_in_use,
    skill_anchors,
    warmup,
)

__all__ = ["describe_skills", "get_skill", "list_skills", "scopes_in_use",
           "skill_anchors", "warmup"]
