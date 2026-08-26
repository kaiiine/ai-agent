"""Réduction du bruit des bibliothèques tierces dans l'interface.

`main.py` fait déjà taire stderr et les `warnings` — mais seulement pendant la
phase d'IMPORT, le temps que le boot loader tourne. Les journaux émis à chaque
appel LLM passent donc à travers, et s'affichent en plein milieu du TUI.
"""
from __future__ import annotations

import logging

#: Journaux tiers dont les avertissements n'apprennent rien à l'utilisateur.
#:
#: Ne mettre ici que ce qui a été VÉRIFIÉ inoffensif : taire un journal, c'est
#: renoncer à ce qu'il dise un jour quelque chose d'utile. Le niveau reste à
#: ERROR, jamais CRITICAL — une vraie panne doit continuer de passer.
_BAVARDS: dict[str, int] = {
    # Gemini n'accepte qu'un SOUS-ENSEMBLE de JSON Schema pour ses déclarations
    # de fonctions. Le convertisseur jette les clés qu'il ne connaît pas
    # (`$schema`, `additionalProperties`, `$defs`) et journalise une ligne par
    # clé, par outil, à CHAQUE appel — soit des dizaines par tour.
    #
    # Vérifié avant de le taire, plutôt que supposé : la conversion RÉSOUT
    # `$defs`/`$ref` avant de les jeter. Le schéma imbriqué d'`ask_clarification`
    # (une liste d'objets `Question`) arrive intact chez Gemini, avec ses
    # `properties`, `required` et `type`. Seules des clés de CONTRAINTE
    # disparaissent — rien de structurel.
    "langchain_google_genai": logging.ERROR,
}


def taire_les_bavards() -> None:
    """À appeler une fois au démarrage, après les imports lourds."""
    for nom, niveau in _BAVARDS.items():
        logging.getLogger(nom).setLevel(niveau)
