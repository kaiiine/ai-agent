"""Distinguer ce qu'AXON se dit à lui-même de ce que l'utilisateur a écrit.

Plusieurs nœuds réinjectent un `HumanMessage` dans la conversation : le compte
rendu d'une revue, le rapport de l'agent de code, celui de la recherche
approfondie, la décision prise sur un plan. Le rôle `human` est le bon — ce sont
des faits qui arrivent au modèle comme une entrée, jamais comme son propre tour.

Mais rien ne les distinguait d'un vrai tour d'utilisateur. À la relecture d'un
thread, ils étaient réaffichés avec le chevron, plomberie comprise : on lisait
« › Résultat de l'agent de code… [SPECIALIST-TRACE] … Restitue-le à l'utilisateur
sans rien y ajouter » comme si l'utilisateur l'avait tapé.

On les MARQUE plutôt que de les reconnaître au texte : une consigne reformulée ne
doit pas ressortir à l'écran.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

_MARQUE = "axon_interne"


def note(texte: str) -> HumanMessage:
    return HumanMessage(content=texte, additional_kwargs={_MARQUE: True})


def est_interne(message: Any) -> bool:
    extra = getattr(message, "additional_kwargs", None)
    return bool(isinstance(extra, dict) and extra.get(_MARQUE))
