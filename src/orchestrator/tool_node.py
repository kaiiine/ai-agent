# src/orchestrator/tool_node.py
"""Exécution des outils, avec cache de session et échecs non fatals.

Une seule question : ce résultat est-il déjà connu, et sinon comment exécuter
sans qu'une exception coûte le tour entier ?
"""
from __future__ import annotations

from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode

from src.orchestrator.resilience import tool_error_to_message

def _refus_mode_plan(tool_calls: list) -> list[ToolMessage]:
    """Le mode plan retirait les outils d'écriture de la LIAISON seulement.

    Ça tenait tant que le modèle ignorait les noms non liés. Le catalogue les lui
    donne tous, et un modèle qui lit un nom l'appelle directement — vérifié sur
    gpt-oss:120b, qui appelle `get_weather_by_city` retiré de sa sélection au lieu
    de le réclamer. Le ToolNode exécute tout ce qu'on lui a enregistré : 30 des 36
    outils bloqués restaient donc joignables, `gmail_send_email` et `shell_run`
    compris. La liaison est un tri, pas une barrière ; la barrière est ici.
    """
    from src.ui.plan_mode import BLOCKED_TOOLS, is_active

    if not is_active():
        return []
    return [
        ToolMessage(
            content=f"`{tc['name']}` écrit — refusé en mode plan. "
                    f"Décris l'action dans le plan au lieu de l'exécuter.",
            tool_call_id=tc["id"], name=tc["name"], status="error",
        )
        for tc in tool_calls if tc["name"] in BLOCKED_TOOLS
    ]


class CachedToolNode:
    """Wraps LangGraph's ToolNode with session-level result caching.
    If ALL tool calls in a batch are cached, skips execution entirely.
    Otherwise executes normally and caches eligible results.
    """

    def __init__(self, tools: list) -> None:
        from src.infra.tools_cache import CACHEABLE_TOOLS, session_cache

        self._inner = ToolNode(tools=tools, handle_tool_errors=tool_error_to_message)
        self._cache = session_cache
        self._cacheable = CACHEABLE_TOOLS

    def __call__(self, state: dict, config=None) -> dict:
        messages = state.get("messages") or []
        # Le dernier message PORTEUR d'appels, pas le dernier message : un nœud de
        # demande a pu répondre à l'un d'eux avant nous, et l'état se termine
        # alors par son résultat.
        last = next((m for m in reversed(messages)
                     if getattr(m, "tool_calls", None)), None)
        repondus = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
        tool_calls = [tc for tc in (getattr(last, "tool_calls", None) or [])
                      if tc["id"] not in repondus]
        if not tool_calls:
            return {"messages": []}
        # Un lot peut mêler une lecture et une écriture : refuser le lot entier
        # laisserait des `tool_call` sans réponse, ce que les providers rejettent.
        refus = _refus_mode_plan(tool_calls)
        if refus:
            bloques = {m.tool_call_id for m in refus}
            tool_calls = [tc for tc in tool_calls if tc["id"] not in bloques]
            if not tool_calls:
                return {"messages": refus}

        if len(tool_calls) != len(last.tool_calls):
            # Réexécuter un appel déjà servi produirait un second résultat pour le
            # même identifiant : `clarifier_appel` a posé la question, l'outil la
            # reposerait.
            rang = messages.index(last)
            state = {**state, "messages": list(messages[:rang])
                     + [last.model_copy(update={"tool_calls": tool_calls})]}

        # Attempt full-batch cache hit
        cached_msgs: list[ToolMessage] = []
        for tc in tool_calls:
            name, args = tc["name"], tc.get("args", {})
            if name not in self._cacheable:
                cached_msgs = []
                break
            hit = self._cache.get(name, args)
            if hit is None:
                cached_msgs = []
                break
            cached_msgs.append(
                ToolMessage(content=hit, tool_call_id=tc["id"], name=name)
            )

        if cached_msgs:
            return {"messages": refus + cached_msgs}

        # Execute and cache eligible results
        result = self._inner.invoke(state, config or {})
        tc_by_id = {tc["id"]: tc for tc in tool_calls}

        for msg in result.get("messages", []):
            if not isinstance(msg, ToolMessage):
                continue
            tc = tc_by_id.get(msg.tool_call_id)
            if tc and tc["name"] in self._cacheable:
                from src.infra.tools_cache import CACHE_TTLS

                self._cache.set(
                    tc["name"], tc.get("args", {}), msg.content, CACHE_TTLS[tc["name"]]
                )
            if tc:
                self._cache.on_tool_executed(tc["name"])

        # Redact sensitive data before it enters the LLM context on cloud backends
        from src.infra.redactor import is_sensitive_path, redact, should_redact
        from src.infra.settings import settings

        if should_redact(settings.llm_backend):
            cleaned: list[ToolMessage] = []
            for msg in result.get("messages", []):
                if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                    tc = tc_by_id.get(msg.tool_call_id, {})
                    args = tc.get("args", {}) if tc else {}
                    path = args.get("path", "") or args.get("file_path", "")
                    content = redact(msg.content)
                    if is_sensitive_path(path) and len(content) > 50:
                        content = "[contenu redacté — fichier sensible non transmis au LLM cloud]"
                    msg = ToolMessage(
                        content=content,
                        tool_call_id=msg.tool_call_id,
                        name=getattr(msg, "name", None),
                        # L'artefact porte le résultat non textuel (images,
                        # ressources) : le reconstruire sans lui le perdrait
                        # silencieusement, ce que la redaction ne demande pas.
                        artifact=getattr(msg, "artifact", None),
                        status=getattr(msg, "status", "success"),
                    )
                cleaned.append(msg)
            result = {"messages": cleaned}

        if refus:
            result = {**result, "messages": refus + list(result.get("messages", []))}
        return result
