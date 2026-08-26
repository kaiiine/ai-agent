from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from src.orchestrator.graph import build_orchestrator
        _orchestrator = build_orchestrator()
    return _orchestrator


def sse_chunk(text: str, cid: str, finish_reason: str | None = None) -> str:
    payload = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "axon",
        "choices": [
            {
                "index": 0,
                "delta": {"content": text} if text else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n"


def content_str(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return str(content)


async def text_lines_to_sse(lines: AsyncIterator[str], cid: str | None = None) -> AsyncIterator[str]:
    """Wrap un itérateur de texte brut en SSE OpenAI."""
    if cid is None:
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    async for text in lines:
        if text:
            yield sse_chunk(text, cid)
    yield sse_chunk("", cid, finish_reason="stop")
    yield "data: [DONE]\n\n"


def _demande_en_attente(orchestrator, config):
    """La demande que le graphe attend sur ce fil, ou None."""
    from src.orchestrator.hitl import Demande

    try:
        instantane = orchestrator.get_state(config)
    except Exception:
        return None
    for tache in getattr(instantane, "tasks", ()) or ():
        for interruption in getattr(tache, "interrupts", ()) or ():
            valeur = getattr(interruption, "value", None)
            if isinstance(valeur, dict) and valeur.get("questions") is not None:
                return Demande.depuis(valeur)
    return None


def _rendre_demande(demande) -> str:
    """La demande rendue en texte : aperçu, questions, choix possibles.

    Une API de chat n'a pas de canal interactif : la question est dite, le tour
    se termine, et le message suivant de l'utilisateur y répond.
    """
    morceaux: list[str] = []
    if demande.apercu.strip():
        morceaux += [demande.apercu.strip(), ""]
    for question in demande.questions:
        morceaux.append(question.texte)
        if question.choix:
            morceaux.append("Réponds par : " + " · ".join(question.choix))
        morceaux.append("")
    return "\n".join(morceaux).strip()


async def stream_orchestrator(user_message: str, thread_id: str) -> AsyncIterator[str]:
    """Stream la réponse de l'orchestrateur LangGraph en SSE OpenAI."""
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}

    orchestrator = get_orchestrator()

    # Un fil qui attend : le message reçu est la réponse, pas une question.
    if _demande_en_attente(orchestrator, config) is not None:
        from src.orchestrator.hitl import reponse as _reponse_hitl
        state = _reponse_hitl([user_message])
    else:
        state = {"messages": [{"role": "user", "content": user_message}]}
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _run() -> None:
        try:
            for msg, _ in orchestrator.stream(state, stream_mode="messages", config=config):
                if isinstance(msg, ToolMessage):
                    continue
                if isinstance(msg, (AIMessageChunk, AIMessage)):
                    text = content_str(msg.content)
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, f"\n\n[Axon erreur : {exc}]")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, _run)

    while True:
        token = await queue.get()
        if token is None:
            break
        yield sse_chunk(token, cid)

    # Sans ce bloc, le tour se termine sur un silence et le client ignore
    # qu'on l'attend.
    _demande = _demande_en_attente(orchestrator, config)
    if _demande is not None:
        yield sse_chunk("\n\n" + _rendre_demande(_demande), cid)

    yield sse_chunk("", cid, finish_reason="stop")
    yield "data: [DONE]\n\n"
