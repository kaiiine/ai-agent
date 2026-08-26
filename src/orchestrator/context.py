# src/orchestrator/context.py
"""Budget de contexte : mesurer, décider quoi garder, compresser le reste.

Une seule question : ces messages tiennent-ils dans la fenêtre du backend, et
sinon que sacrifier en premier ? Rien ici ne connaît le graphe — toutes les
dépendances (LLM, backend) arrivent en paramètre, ce qui rend l'ensemble
testable sans orchestrateur.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

_CONTEXT_LIMITS: dict[str, int] = {
    "ollama": 131_072,
    "ollama_cloud": 131_072,   
    "groq": 131_072,
    "gemini": 1_048_576,       
    "mistral": 128_000,
    "nvidia": 128_000,
}

_CONTEXT_LIMIT_DEFAUT = 128_000

_COMPACTION_BUFFER = 20_000

_PRUNE_PROTECT = 40_000

_PRUNE_MINIMUM = 12_000

_BACKEND_POLICY = {
    "ollama": {"ratio": 0.40, "keep_recent": 6},
    "ollama_cloud": {"ratio": 0.70, "keep_recent": 12},
    "gemini": {"ratio": 0.75, "keep_recent": 24},
    "mistral": {"ratio": 0.60, "keep_recent": 8},
    "groq": {"ratio": 0.65, "keep_recent": 12},
    "nvidia": {"ratio": 0.60, "keep_recent": 8},
}

_SUMMARY_MARKER = "[COMPRESSED SESSION MEMORY]"

_MAX_TOOL_MSG_CHARS = 3_000

_TOKENS_PAR_MESSAGE = 4          
_CHARS_PAR_TOKEN_DEFAUT = 3      


@lru_cache(maxsize=1)
def _encodeur():
    """Tokenizer BPE réel, chargé une fois. `None` si indisponible.

    `o200k_base` est celui d'OpenAI ; Gemini, Mistral et les modèles Ollama ont
    le leur. Ça reste donc une approximation — mais d'un tout autre ordre que le
    comptage au caractère : tous les BPE modernes découpent de façon comparable,
    là où un ratio fixe ignore la langue et la nature du texte.
    """
    try:
        import tiktoken
        return tiktoken.get_encoding("o200k_base")
    except Exception:
        return None


def _estimate_tokens(messages: List) -> int:
    """Taille d'une conversation en tokens.

    Comptait auparavant `len(texte) // 3`. Mesuré contre un vrai tokenizer, ce
    ratio SURESTIME de 6 % à 74 % — typiquement +45 % sur du français et du code,
    parce que trois caractères par token est une hypothèse d'anglais dense.

    La conséquence n'était pas cosmétique : le même compteur décide du seuil de
    compression. On compressait donc bien avant d'en avoir besoin, en sacrifiant
    du contexte encore disponible.
    """
    enc = _encodeur()
    total = 0
    for m in messages:
        content = m.content if isinstance(m.content, str) else str(m.content)
        morceaux = [content] + [str(tc) for tc in (getattr(m, "tool_calls", None) or [])]
        for texte in morceaux:
            if enc is not None:
                total += len(enc.encode(texte, disallowed_special=()))
            else:
                total += max(1, len(texte) // _CHARS_PAR_TOKEN_DEFAUT)
        total += _TOKENS_PAR_MESSAGE
    return total

def _backend_policy(backend: str) -> dict:
    return _BACKEND_POLICY.get(
        backend,
        {"ratio": 0.6, "keep_recent": 10},
    )

def _usable_budget(backend: str) -> int:
    policy = _backend_policy(backend)
    return int(_CONTEXT_LIMITS.get(backend, _CONTEXT_LIMIT_DEFAUT) * policy["ratio"])

def _should_compress(messages: List, backend: str) -> bool:
    effective = [
        m
        for m in messages
        if not (isinstance(m, SystemMessage) and _SUMMARY_MARKER in str(m.content))
    ]
    return _estimate_tokens(effective) > _usable_budget(backend)

def _cap_tool_messages(messages: List) -> List:
    out = []

    for m in messages:
        if (
            isinstance(m, ToolMessage)
            and isinstance(m.content, str)
            and len(m.content) > _MAX_TOOL_MSG_CHARS
        ):
            content = m.content.strip()

            head_size = int(_MAX_TOOL_MSG_CHARS * 0.75)
            tail_size = _MAX_TOOL_MSG_CHARS - head_size

            content = (
                content[:head_size] + "\n...[truncated]...\n" + content[-tail_size:]
            )

            m = ToolMessage(
                content=content,
                tool_call_id=m.tool_call_id,
                name=getattr(m, "name", None),
            )

        out.append(m)

    return out

def _drop_smartest(messages: List) -> List | None:
    """Drop the oldest tool round (AIMessage + its ToolMessages) first.
    Falls back to dropping the oldest non-system message if no tool round found."""
    start = 1 if messages and isinstance(messages[0], SystemMessage) else 0

    for i in range(start, len(messages)):
        m = messages[i]
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            # Find where the tool results for this round end
            j = i + 1
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                j += 1
            if j > i + 1:
                return messages[:i] + messages[j:]

    # No complete tool round found — drop oldest non-system, non-human message
    for i in range(start, len(messages)):
        if not isinstance(messages[i], HumanMessage):
            return messages[:i] + messages[i + 1 :]

    return None

_CODING_KEYWORDS = frozenset(
    {
        "code",
        "fichier",
        "file",
        "fonction",
        "function",
        "composant",
        "component",
        "bug",
        "fix",
        "erreur",
        "error",
        "npm",
        "pnpm",
        "yarn",
        "git",
        "migration",
        "supabase",
        "next",
        "react",
        "vue",
        "svelte",
        "angular",
        "typescript",
        "python",
        "shell",
        "terminal",
        "build",
        "deploy",
        "css",
        "html",
        "sql",
        "api",
        "endpoint",
    }
)


def _is_coding_session(messages: List) -> bool:
    """Detect if the session is code-related based on message content."""
    for m in messages:
        if isinstance(m, HumanMessage):
            content = str(m.content).lower()
            if any(kw in content for kw in _CODING_KEYWORDS):
                return True
    return False


def _compress_context(
    messages: List, llm, backend: str = "ollama_cloud"
) -> tuple[List, List]:
    """Compress old context while preserving recent raw messages.
    Removes old summaries, compresses old conversation, keeps recent messages raw.
    Uses a coding-specific prompt or a general one based on session content.
    """
    # Collect old summaries to remove from LangGraph state
    old_summaries = [
        m
        for m in messages
        if isinstance(m, SystemMessage) and _SUMMARY_MARKER in str(m.content)
    ]

    clean_messages = [m for m in messages if m not in old_summaries]

    system_msg = (
        clean_messages[0]
        if clean_messages and isinstance(clean_messages[0], SystemMessage)
        else None
    )

    conversation = [m for m in clean_messages if not isinstance(m, SystemMessage)]

    keep_recent = _backend_policy(backend)["keep_recent"]

    if len(conversation) <= keep_recent:
        # Nothing to compress — but still remove old summaries if any
        if old_summaries:
            return clean_messages, old_summaries
        return messages, []

    old = conversation[:-keep_recent]
    recent = conversation[-keep_recent:]

    last_human = next(
        (m for m in reversed(conversation) if isinstance(m, HumanMessage)),
        None,
    )
    if last_human and last_human not in recent:
        recent = [last_human] + recent[:-1]

    # Build transcript of old messages
    transcript_parts = []
    for m in old:
        content = m.content if isinstance(m.content, str) else str(m.content)
        if isinstance(m, HumanMessage):
            transcript_parts.append(f"[USER]: {content[:4000]}")
        elif isinstance(m, AIMessage):
            if content.strip():
                transcript_parts.append(f"[ASSISTANT]: {content[:2500]}")
            for tc in getattr(m, "tool_calls", []) or []:
                args_str = str(tc.get("args", {}))[:1200]
                transcript_parts.append(
                    f"[TOOL CALL] {tc.get('name', '?')}({args_str})"
                )
        elif isinstance(m, ToolMessage):
            name = getattr(m, "name", "tool") or "tool"
            transcript_parts.append(f"[TOOL RESULT] {name}: {content[:2000]}")

    transcript = "\n".join(transcript_parts)

    # Select prompt based on session type
    is_coding = _is_coding_session(conversation)

    if is_coding:
        prompt = f"""
You are the memory module of a coding AI agent.

Compress the old context below to free tokens without losing task continuity.

Rules:
- Be dense, technical, and structured.
- Do NOT retell the conversation.
- Preserve exact paths, filenames, commands, errors, and decisions.
- Clearly distinguish completed work from remaining work.
- If information is unknown, write "unknown".

Required format:

# User Objective
...

# Current State
- cwd:
- backend:
- mode:
- git branch:
- status:

# Plan
## Completed
- ...
## Remaining
- ...

# Important Files
## Read
- path: useful content
## Modified/Created
- path: exact change
## To Modify
- path: intention

# Executed Commands
- command → useful result

# Errors / Blockers
- error → cause → status

# Technical Decisions
- decision → reason

# Exact Resume Point
Describe precisely what the agent should do next.

OLD CONTEXT:
{transcript}
"""
    else:
        prompt = f"""
You are a memory assistant. Compress the conversation below into a dense summary
that preserves all key information needed to continue the conversation.

Rules:
- Be concise and factual.
- Preserve decisions, conclusions, and action items.
- Keep user preferences and constraints.
- Note what was asked and what was answered.
- If something is unknown or unclear, say so.

Required format:

# Conversation Summary
Brief overview of the conversation.

# Key Facts & Decisions
- ...

# User Preferences & Constraints
- ...

# Current Task / Next Step
What the user is trying to accomplish and where things stand.

# Unresolved Questions
- ...

OLD CONTEXT:
{transcript}
"""

    try:
        summary_response = llm.invoke([HumanMessage(content=prompt)])
        summary_content = summary_response.content

        if isinstance(summary_content, list):
            summary_content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in summary_content
            )

        summary_msg = SystemMessage(content=f"{_SUMMARY_MARKER}\n{summary_content}")

        compressed = ([system_msg] if system_msg else []) + [summary_msg] + recent
        # Return old conversation messages + old summaries as "removed"
        return compressed, old + old_summaries

    except Exception:
        dropped = _drop_smartest(messages) or messages
        kept_ids = {id(m) for m in dropped}
        removed = [m for m in messages if id(m) not in kept_ids]
        return dropped, removed + old_summaries
