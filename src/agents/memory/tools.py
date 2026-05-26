"""axon_note — outil de mémoire persistante par projet.

Le LLM appelle axon_note() quand il découvre ou fait quelque chose
d'important que les futurs threads sur ce repo doivent connaître.

Les notes sont écrites dans {git_root}/.axon/memory/<kind>.md et injectées
automatiquement dans le system prompt au prochain lancement.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool("axon_note")
def axon_note(fact: str, kind: str = "learning") -> str:
    """
    Sauvegarde un fait important dans la mémoire persistante du projet.

    Utilise ce tool quand tu :
    - découvres quelque chose de non-évident sur la structure du projet
    - fais un changement significatif que les prochaines sessions doivent connaître
    - enregistres une décision technique et sa raison
    - notes une contrainte ou un comportement surprenant

    La note sera disponible automatiquement dans les futurs threads Axon
    sur ce projet — sans que l'utilisateur ait besoin de re-expliquer.

    Exemples de bons faits à noter :
    - "Auth refactorisée vers JWT RS256. Voir src/auth/tokens.py"
    - "La DB est PostgreSQL 15, migrations dans alembic/versions/"
    - "Ne pas utiliser assert en prod — converti en RuntimeError partout"
    - "L'API externe /orders retourne parfois HTTP 202 sans body — géré dans orders.py:88"

    Args:
        fact: phrase concise décrivant le fait, la découverte ou le changement
        kind: "decision" | "learning" | "blocker" | "eval" (défaut: "learning")
    Returns:
        confirmation d'écriture
    """
    from src.agents.memory.persistent import write_single_entry
    return write_single_entry(kind, fact)
