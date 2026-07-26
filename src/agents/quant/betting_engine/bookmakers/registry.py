"""Registre des connecteurs bookmaker (§4.1 du PRD).

Un seul bookmaker en v1 (Winamax). Ajouter Betclic/Unibet plus tard = créer
`bookmakers/<nom>/` implémentant `BookmakerConnector` et l'enregistrer ici —
sans toucher au reste du pipeline. Aucun dossier vide anticipé pour les autres.
"""

from __future__ import annotations

from .protocol import BookmakerConnector
from .winamax.connector import WinamaxConnector

BOOKMAKERS: dict[str, BookmakerConnector] = {
    "winamax": WinamaxConnector(),
}


def get_connector(name: str) -> BookmakerConnector:
    """Renvoie le connecteur enregistré ou lève une erreur explicite."""
    try:
        return BOOKMAKERS[name.lower()]
    except KeyError:
        raise KeyError(
            f"Bookmaker « {name} » non enregistré. Connus : {sorted(BOOKMAKERS)}."
        ) from None
