"""
Axon API Server — serveur OpenAI-compatible pour Zed, Cursor, Continue.dev…

Lancement :
    python src/api_server.py          # port 8765
    python src/api_server.py --port 9000

Configuration Zed (~/.config/zed/settings.json) :
    "language_models": {
      "openai": {
        "api_url": "http://127.0.0.1:8765/v1",
        "available_models": [
          {"name": "axon", "max_tokens": 128000, "max_output_tokens": 8192}
        ]
      }
    }
    → sélectionner "axon (openai)" dans le panneau AI

Configuration Continue.dev (config.json) :
    {"models": [{"title": "Axon", "provider": "openai", "model": "axon",
                 "apiBase": "http://127.0.0.1:8765/v1", "apiKey": "axon"}]}

Slash commands supportées depuis Zed :
    /help  /keys  /backend  /model  /graph  /build
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

from src.api.models import ChatRequest
from src.api.streaming import stream_orchestrator, text_lines_to_sse, sse_chunk
from src.api.commands import dispatch, is_command, parse

app = FastAPI(title="Axon", version="1.0.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ── /v1/models ────────────────────────────────────────────────────────────────

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "axon",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "axon",
                "context_window": 128_000,
            }
        ],
    }


# ── /v1/chat/completions ──────────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps JSON invalide")

    req = ChatRequest(**body)
    thread_id = request.headers.get("X-Thread-Id", "api-default")

    user_msg = next(
        (m.text() for m in reversed(req.messages) if m.role == "user"),
        None,
    )
    if not user_msg:
        raise HTTPException(status_code=400, detail="Aucun message utilisateur trouvé")

    # Slash command → handler dédié
    if is_command(user_msg):
        cmd, args = parse(user_msg)
        lines = dispatch(cmd, args, thread_id)
        stream = text_lines_to_sse(lines)
    else:
        stream = stream_orchestrator(user_msg, thread_id)

    if req.stream:
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Mode non-streaming : accumule la réponse complète
    full = ""
    async for chunk in stream:
        if chunk.startswith("data: {"):
            try:
                data = json.loads(chunk[6:])
                full += data["choices"][0]["delta"].get("content", "")
            except Exception:
                pass

    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "axon",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": full}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


# ── /health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "axon"}


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    print(f"Axon API  →  http://{args.host}:{args.port}/v1")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
