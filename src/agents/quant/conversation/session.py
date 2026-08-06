"""Contraintes de pari persistées PAR FIL de conversation (§11, §12).

Le dump montre la boucle : l'utilisateur répond « tous les sports, toutes les
compétitions », et la question revient au tour suivant. La réponse existait, mais
seulement comme du texte dans l'historique — donc à re-comprendre à chaque tour.

Ici elle est un objet, rangé sous l'identifiant du fil. Le tour suivant le relit
au lieu de le redemander. Portée : le processus courant — un redémarrage repart
d'un state vide, ce qui est le comportement correct (une bankroll d'hier n'est
pas une bankroll d'aujourd'hui).
"""

from __future__ import annotations

import threading
from typing import Any

from .constraints import UserBettingConstraints

_LOCK = threading.Lock()
_ETAT: dict[str, UserBettingConstraints] = {}

DEFAULT_THREAD = "_sans_fil"


def thread_id(config: Any) -> str:
    """Identifiant de fil issu du `RunnableConfig`. Sans fil identifiable, tout
    retombe sur une clé commune — dégradé, jamais fusionné par erreur avec un
    autre fil réel."""
    try:
        value = (config or {}).get("configurable", {}).get("thread_id")
    except AttributeError:
        value = None
    return str(value) if value else DEFAULT_THREAD


def load(thread: str) -> UserBettingConstraints | None:
    with _LOCK:
        return _ETAT.get(thread)


def store(thread: str, constraints: UserBettingConstraints) -> None:
    with _LOCK:
        _ETAT[thread] = constraints


def reset(thread: str | None = None) -> None:
    """Vide un fil, ou tous. Utilisé par les tests et par un changement de fil."""
    with _LOCK:
        if thread is None:
            _ETAT.clear()
        else:
            _ETAT.pop(thread, None)
