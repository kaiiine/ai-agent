# src/orchestrator/tool_node.py
"""Exécution des outils, avec cache de session et échecs non fatals.

Une seule question : ce résultat est-il déjà connu, et sinon comment exécuter
sans qu'une exception coûte le tour entier ?
"""
from __future__ import annotations

import json
import time

from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode

from src.infra import trace
from src.orchestrator.resilience import tool_error_to_message

#: Statut rendu par un outil → (verdict de policy, ce qu'il est advenu).
#:
#: Un refus REND un statut, il ne lève pas. C'est ce qui a permis à une tâche cron
#: de loguer « ok » alors que toutes ses commandes avaient été bloquées : le
#: statut était là, personne ne le lisait. Ici on le lit une fois, au seul
#: endroit où tous les résultats d'outils passent.
_VERDICTS: dict[str, tuple[str, str]] = {
    "blocked": (trace.REFUSE, trace.BLOQUE),
    "requires_confirmation": (trace.A_CONFIRMER, trace.BLOQUE),
    "error": (trace.AUTORISE, trace.ERREUR),
}


def _verdict(message: ToolMessage) -> tuple[str, str, str]:
    """(policy, résultat, code d'erreur) d'un résultat d'outil.

    Le code d'erreur est COURT et stable — ce qui se compte doit se grouper. Un
    message complet ne se regroupe pas : deux fois la même panne donne deux
    lignes distinctes, et le total se perd.
    """
    if getattr(message, "status", "") == "error":
        return trace.AUTORISE, trace.ERREUR, "tool_error"
    contenu = message.content
    if not isinstance(contenu, str) or not contenu.strip().startswith("{"):
        return trace.AUTORISE, trace.OK, ""
    try:
        charge = json.loads(contenu)
    except (ValueError, TypeError):
        return trace.AUTORISE, trace.OK, ""
    if not isinstance(charge, dict):
        return trace.AUTORISE, trace.OK, ""
    statut = str(charge.get("status") or "")
    policy, resultat = _VERDICTS.get(statut, (trace.AUTORISE, trace.OK))
    code = statut if resultat != trace.OK else ""
    return policy, resultat, code


def _inscrire_les_appels(messages: list, tc_by_id: dict, *,
                         latence_ms: int, lot: int, cache: bool = False) -> None:
    """Une ligne de trace par outil exécuté. Ne juge rien, lit ce qui est rendu.

    Enveloppée comme `trace.inscrire` l'est : ce chemin passe par `src.ui.journal`
    pour nommer la cible, et un journal qui casse le tour qu'il observe serait
    précisément le défaut que la trace existe pour montrer. Ici la conséquence
    serait pire qu'une ligne perdue — le lot d'outils entier échouerait.
    """
    try:
        _inscrire(messages, tc_by_id, latence_ms=latence_ms, lot=lot, cache=cache)
    except Exception:                                            # noqa: BLE001
        pass


def _inscrire(messages: list, tc_by_id: dict, *,
              latence_ms: int, lot: int, cache: bool) -> None:
    from src.ui.journal import cible_de_l_appel

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        appel = tc_by_id.get(msg.tool_call_id) or {}
        policy, resultat, code = _verdict(msg)
        trace.inscrire(trace.Action(
            genre=trace.OUTIL,
            outil=str(appel.get("name") or getattr(msg, "name", "") or ""),
            cible=cible_de_l_appel(appel.get("args") or {})[:200],
            policy=policy,
            resultat=trace.CACHE if cache else resultat,
            erreur=code,
            # La latence est celle du LOT : `ToolNode` exécute le lot entier en
            # un appel, et découper ce temps entre les appels serait inventé.
            # Au-delà d'un appel, on ne l'attribue à aucun.
            latence_ms=latence_ms if lot == 1 else 0,
            verification=trace.NON_VERIFIE,
            extra={"lot": lot} if lot > 1 else {},
        ))


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
            for _msg in refus:
                trace.inscrire(trace.Action(
                    genre=trace.OUTIL, outil=str(getattr(_msg, "name", "") or ""),
                    policy=trace.REFUSE, resultat=trace.BLOQUE, erreur="plan_mode",
                    verification=trace.NON_VERIFIE))
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
            _inscrire_les_appels(cached_msgs, {tc["id"]: tc for tc in tool_calls},
                                 latence_ms=0, lot=len(cached_msgs), cache=True)
            return {"messages": refus + cached_msgs}

        # Execute and cache eligible results
        _depart = time.monotonic()
        result = self._inner.invoke(state, config or {})
        _latence = int((time.monotonic() - _depart) * 1000)
        tc_by_id = {tc["id"]: tc for tc in tool_calls}
        _inscrire_les_appels(result.get("messages", []), tc_by_id,
                             latence_ms=_latence, lot=len(tool_calls))

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
