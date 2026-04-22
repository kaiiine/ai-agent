"""axon_note — outil de mémoire persistante par projet.

Le LLM appelle axon_note() quand il découvre ou fait quelque chose
d'important que les futurs threads sur ce repo doivent connaître.

Les notes sont écrites dans {git_root}/.axon/memory.md et injectées
automatiquement dans le system prompt au prochain lancement.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool


def _find_git_root(start: Path) -> Path:
    """Remonte depuis start jusqu'à trouver un .git. Retourne start si absent."""
    for directory in [start, *start.parents]:
        if (directory / ".git").exists():
            return directory
    return start


def _memory_path() -> Path:
    root = _find_git_root(Path.cwd())
    return root / ".axon" / "memory.md"


@tool("axon_note")
def axon_note(fact: str) -> str:
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
    Returns:
        confirmation d'écriture
    """
    p = _memory_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {date_str}\n{fact.strip()}\n"

    with p.open("a", encoding="utf-8") as f:
        if p.stat().st_size == 0:
            # Premier appel sur ce projet — écrire l'en-tête
            project_name = p.parent.parent.name
            f.write(f"# Axon Memory — {project_name}\n")
            f.write("*Généré automatiquement. Ne pas éditer manuellement.*\n")
        f.write(entry)

    return f"Note enregistrée dans {p}"
