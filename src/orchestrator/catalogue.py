"""Le catalogue dit ce qui EXISTE ; les schémas disent comment s'en servir.

Un schéma coûte ~446 tokens, une ligne de catalogue ~20. Lier les 104 outils est
hors budget ; les NOMMER tous tient dans le préfixe du prompt, qui ne change pas
d'un tour à l'autre et se met donc en cache.

C'est la pièce qui manquait. Le retriever sert le bon groupe 82 % du temps, mais
l'outil exact bien moins souvent — et jusqu'ici le modèle n'avait aucun moyen de
savoir qu'un outil lui manquait : il ne voyait que sa sélection. Il concluait donc
que la capacité n'existait pas, et expliquait à l'utilisateur comment faire à la
main. Avec le catalogue sous les yeux il lit le nom qui manque et le réclame.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool as lc_tool

# Au-delà, un modèle en difficulté ouvre outil sur outil et réintroduit
# exactement le coût que la sélection évitait.
OUVERTURES_MAX = 3

_RESUME_MAX = 110

_par_nom: dict[str, BaseTool] = {}


def _resume(outil: BaseTool) -> str:
    """La première ligne utile de la description, sans le mode d'emploi qui suit."""
    for ligne in (outil.description or "").splitlines():
        ligne = " ".join(ligne.split())
        if ligne:
            return ligne[:_RESUME_MAX]
    return outil.name


def indexer(outils: list[BaseTool]) -> None:
    _par_nom.clear()
    _par_nom.update({o.name: o for o in outils})


def connu(nom: str) -> bool:
    return nom in _par_nom


def outil(nom: str) -> BaseTool | None:
    return _par_nom.get(nom)


def menu(exclus: frozenset[str] = frozenset()) -> str:
    return "\n".join(
        f"{nom}: {_resume(o)}"
        for nom, o in sorted(_par_nom.items())
        if nom not in exclus and nom != "obtenir_outil"
    )


@lc_tool("obtenir_outil")
def obtenir_outil(nom: str) -> str:
    """Rend disponible un outil du CATALOGUE absent de ta sélection.

    Args:
        nom: le nom exact tel qu'il figure au catalogue
    Returns:
        confirmation — l'outil sera appelable au tour suivant
    """
    from src.ui.plan_mode import BLOCKED_TOOLS, is_active

    nom = (nom or "").strip()
    if not connu(nom):
        return (f"`{nom}` ne figure pas au catalogue. Reprends un nom exact de la "
                f"liste, ou appelle ask_clarification si aucun ne convient.")
    # Le mode plan retire les outils d'écriture de la sélection : sans ce garde,
    # les réclamer par leur nom rouvrait la porte que le mode venait de fermer.
    if is_active() and nom in BLOCKED_TOOLS:
        return f"`{nom}` écrit — indisponible en mode plan. Décris l'action dans le plan."
    return f"`{nom}` est disponible. Appelle-le maintenant."


def ouverts(messages: list) -> list[str]:
    """Les outils réclamés depuis le dernier tour de l'utilisateur.

    Lu dans l'historique plutôt que porté par l'état : le graphe rejoue les
    messages à chaque reprise de checkpoint, l'historique est donc la seule
    source qui survit à un `interrupt()` sans réducteur dédié.
    """
    noms: list[str] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if not isinstance(message, AIMessage):
            continue
        for appel in message.tool_calls or ():
            if appel.get("name") != "obtenir_outil":
                continue
            nom = (appel.get("args") or {}).get("nom", "").strip()
            if connu(nom) and nom not in noms:
                noms.append(nom)
    return noms[:OUVERTURES_MAX]


def serveurs_actifs(messages: list, tours: int = 2) -> set[str]:
    """Serveurs MCP dont la conversation s'est servie dans les derniers tours.

    Sur les 8 usages MCP réels du corpus, 5 sont des tours de suivi qui ne nomment
    rien — « voici l'uid: d76a… », « Extrude le plus ». Sans cette mémoire, la porte
    lexicale n'en sert qu'un seul ; avec elle, cinq.
    """
    vus: set[str] = set()
    restants = tours
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            restants -= 1
            if restants < 0:
                break
            continue
        if not isinstance(message, AIMessage):
            continue
        for appel in message.tool_calls or ():
            nom = appel.get("name") or ""
            if "__" in nom:
                vus.add(nom.split("__")[0])
    return vus
