"""Réduction du bruit des bibliothèques tierces dans l'interface.

`main.py` fait taire stderr et les `warnings`, mais seulement pendant la phase
d'import. Les journaux émis à chaque appel LLM passent à travers et s'affichent
en plein TUI.
"""
from __future__ import annotations

import logging

#: N'y mettre que ce qui a été vérifié inoffensif. Le niveau reste à ERROR,
#: jamais CRITICAL : une vraie panne doit continuer de passer.
_BAVARDS: dict[str, int] = {
    # Une ligne par clé de schéma refusée, par outil, à chaque appel. Inoffensif :
    # la conversion résout `$defs`/`$ref` avant de les jeter, donc les schémas
    # imbriqués arrivent intacts (cf. tests/test_journal_silencieux.py).
    "langchain_google_genai": logging.ERROR,
}


def taire_les_bavards() -> None:
    """À appeler une fois au démarrage, après les imports lourds."""
    for nom, niveau in _BAVARDS.items():
        logging.getLogger(nom).setLevel(niveau)
