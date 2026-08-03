# src/orchestrator/graph.py
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from rich.console import Console as RichConsole

console = RichConsole()

# Certains modèles (minimax-m2.5 notamment — bug connu upstream, cf. issues
# sgl-project/sglang#16057, vllm-project/vllm#28963) émettent parfois leur appel
# d'outil en texte brut avec une balise maison ("xxx:tool_call ... </xxx:tool_call>")
# au lieu du vrai mécanisme de function calling. LangChain ne le reconnaît pas —
# tool_calls reste vide et la commande n'est jamais exécutée.
_MALFORMED_TOOL_CALL_RE = re.compile(r"\w+:tool_call\b.*?</\w+:tool_call>", re.DOTALL | re.IGNORECASE)

# ── Context budget constants ───────────────────────────────────────────────────
_CONTEXT_LIMITS: dict[str, int] = {
    "ollama": 131_072,
    "ollama_cloud": 128_000,
    "groq": 131_072,
    "gemini": 1_000_000,
}
_COMPACTION_BUFFER = 20_000
_PRUNE_PROTECT = 40_000
_PRUNE_MINIMUM = 12_000
_BACKEND_POLICY = {
    "ollama": {"ratio": 0.40, "keep_recent": 6},
    "ollama_cloud": {"ratio": 0.70, "keep_recent": 12},
    "gemini": {"ratio": 0.75, "keep_recent": 24},
    "mistral": {"ratio": 0.60, "keep_recent": 8},
    "groq": {"ratio": 0.65, "keep_recent": 12},
}

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

_SUMMARY_MARKER = "[COMPRESSED SESSION MEMORY]"
_MAX_TOOL_MSG_CHARS = 3_000
_MAX_TOOL_ROUNDS = 12

# ── Compile callback ───────────────────────────────────────────────────────────
_compile_callback = None
_compressed_this_turn: bool = False


def set_compile_callback(fn) -> None:
    global _compile_callback, _compressed_this_turn
    _compile_callback = fn
    _compressed_this_turn = False  # reset at start of each user turn


# ── Language preference ────────────────────────────────────────────────────────
_lang_pref: str = "fr"


def set_lang_pref(lang: str) -> None:
    global _lang_pref
    _lang_pref = lang


def get_lang_pref() -> str:
    return _lang_pref


# ── Last selected tools (for /debug) ──────────────────────────────────────────
_last_selected_tools: list[str] = []


def get_last_selected_tools() -> list[str]:
    return _last_selected_tools


def _on_compress() -> None:
    if _compile_callback:
        _compile_callback()


# ── Tool-round counter ────────────────────────────────────────────────────────


def _consecutive_tool_rounds(messages: List) -> int:
    """Count total AI→Tool rounds since the last HumanMessage (not just consecutive).
    This catches loops where the LLM interleaves text between tool calls to reset the counter."""
    rounds = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            rounds += 1
    return rounds


# ── Token estimation ───────────────────────────────────────────────────────────


def _estimate_tokens(messages: List) -> int:
    total = 0
    for m in messages:
        content = m.content if isinstance(m.content, str) else str(m.content)
        total += max(1, len(content) // 3)
        for tc in getattr(m, "tool_calls", []) or []:
            total += len(str(tc)) // 3
        total += 4
    return total


def _backend_policy(backend: str) -> dict:
    return _BACKEND_POLICY.get(
        backend,
        {"ratio": 0.6, "keep_recent": 10},
    )


def _usable_budget(backend: str) -> int:
    policy = _backend_policy(backend)
    return int(_CONTEXT_LIMITS.get(backend, 128_000) * policy["ratio"])


def _should_compress(messages: List, backend: str) -> bool:
    effective = [
        m
        for m in messages
        if not (isinstance(m, SystemMessage) and _SUMMARY_MARKER in str(m.content))
    ]
    return _estimate_tokens(effective) > _usable_budget(backend)


# ── Context helpers ────────────────────────────────────────────────────────────


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


def _is_coding_session(messages: List) -> bool:
    """Detect if the session is code-related based on message content."""
    for m in messages:
        if isinstance(m, HumanMessage):
            content = str(m.content).lower()
            if any(kw in content for kw in _CODING_KEYWORDS):
                return True
    return False


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


def _sanitize_messages_for_mistral(messages: List) -> List:
    """Mistral requires strict tool_call/tool_result pairing.
    Removes AIMessages with unanswered tool_calls AND ToolMessages
    that became orphaned (e.g. after context compression dropped their parent AIMessage)."""
    all_response_ids = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}

    valid_call_ids: set[str] = set()
    removed_ai: set[int] = set()
    for i, m in enumerate(messages):
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            tc_ids = [tc["id"] for tc in m.tool_calls]
            if all(tid in all_response_ids for tid in tc_ids):
                valid_call_ids.update(tc_ids)
            else:
                removed_ai.add(i)

    return [
        m
        for i, m in enumerate(messages)
        if i not in removed_ai
        and not (isinstance(m, ToolMessage) and m.tool_call_id not in valid_call_ids)
    ]


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


# ── Cached ToolNode ────────────────────────────────────────────────────────────


class CachedToolNode:
    """Wraps LangGraph's ToolNode with session-level result caching.
    If ALL tool calls in a batch are cached, skips execution entirely.
    Otherwise executes normally and caches eligible results.
    """

    def __init__(self, tools: list) -> None:
        from src.infra.tools_cache import CACHEABLE_TOOLS, session_cache

        self._inner = ToolNode(tools=tools)
        self._cache = session_cache
        self._cacheable = CACHEABLE_TOOLS

    def __call__(self, state: dict, config=None) -> dict:
        last = state["messages"][-1] if state.get("messages") else None
        tool_calls = getattr(last, "tool_calls", None) or []

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
            return {"messages": cached_msgs}

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

        return result


# ── Orchestrator ───────────────────────────────────────────────────────────────

from src.infra.checkpoint import build_checkpointer
from src.llm.models import (
    make_llm,
    make_llm_gemini,
    make_llm_groq,
    make_llm_mistral,
    make_llm_ollama_cloud,
    make_orchestrator_llm_with_key,
)
from src.llm.prompts import build_system_prompt
from src.orchestrator.registry import build_all_tools
from src.orchestrator.state import GlobalState
from src.orchestrator.tool_retriever import ToolRetriever


def _ensure_system_prompt(
    messages: List, selected_tools: List, today: str, plan_mode: bool = False
) -> List:
    import os

    user_name = os.getenv("USER_NAME", "l'utilisateur")
    tool_names = [t.name for t in selected_tools]
    system_msg = SystemMessage(
        content=build_system_prompt(
            tool_names, today, user_name, plan_mode=plan_mode, lang=_lang_pref
        )
    )
    if not messages:
        return [system_msg]
    first = messages[0]
    role0 = (
        first.get("type") if isinstance(first, dict) else getattr(first, "type", None)
    )
    if role0 == "system":
        return [system_msg] + messages[1:]
    return [system_msg] + messages


def _chat_node_factory():
    _factories = {
        "groq": make_llm_groq,
        "ollama_cloud": make_llm_ollama_cloud,
        "ollama": make_llm,
        "gemini": make_llm_gemini,
        "mistral": make_llm_mistral,
    }
    tools = build_all_tools()
    retriever = ToolRetriever(tools)

    # Tools MCP : découverts dynamiquement, indexés et routés SÉPARÉMENT des
    # natifs (routing à deux étages avec filtrage par serveur). Ils rejoignent
    # ensuite la même liste : le ToolNode ne fait aucune différence entre les deux.
    # Sans serveur déclaré, `mcp_runtime()` est inerte et ne coûte rien.
    from src.mcp_client.runtime import mcp_runtime

    _mcp = mcp_runtime()
    tools = tools + _mcp.tools

    def chatbot(state: GlobalState):
        from src.infra.settings import settings
        from src.ui.plan_mode import BLOCKED_TOOLS
        from src.ui.plan_mode import is_active as _is_plan_mode

        global _compressed_this_turn
        last = state["messages"][-1] if state["messages"] else None
        if isinstance(last, HumanMessage):
            _compressed_this_turn = False

        # Une bascule automatique (rate-limit) est TEMPORAIRE : si le provider préféré
        # a de nouveau une clé saine, on y revient avant de choisir le backend du tour.
        try:
            from src.llm.key_pool import restore_preferred_backend as _restore
            _restored = _restore(settings)
            if _restored:
                console.print(f"[dim]  ↩  retour au provider préféré : {_restored}[/dim]")
        except Exception:
            pass

        backend = settings.llm_backend
        factory = _factories.get(backend, make_llm_ollama_cloud)

        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        last_message = state["messages"][-1]

        def _content_to_str(content) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            return str(content)

        if last_human:
            query = _content_to_str(last_human.content)
            if len(query.split()) < 8:
                human_msgs = [
                    _content_to_str(m.content)
                    for m in state["messages"]
                    if isinstance(m, HumanMessage)
                ]
                query = " ".join(human_msgs[-3:])
        else:
            query = (
                _content_to_str(last_message.content)
                if hasattr(last_message, "content")
                else str(last_message)
            )
        selected_tools = retriever.get(query) + _mcp.select(query)

        global _last_selected_tools
        _last_selected_tools = [t.name for t in selected_tools]

        # Plan mode — force-include all read-only tools, strip writes
        plan_mode = _is_plan_mode()
        if plan_mode:
            from src.orchestrator.tool_retriever import TOOL_GROUPS

            _read_groups = ("filesystem", "search", "git", "drive", "arxiv", "time")
            _tools_by_name = {t.name: t for t in tools}
            _selected_names = {t.name for t in selected_tools}
            for _g in _read_groups:
                for _tname in TOOL_GROUPS.get(_g, []):
                    if _tname not in _selected_names and _tname in _tools_by_name:
                        selected_tools.append(_tools_by_name[_tname])
            selected_tools = [t for t in selected_tools if t.name not in BLOCKED_TOOLS]

        # Tool-round cap — force text response after _MAX_TOOL_ROUNDS consecutive rounds
        force_text = _consecutive_tool_rounds(state["messages"]) >= _MAX_TOOL_ROUNDS
        if force_text:
            console.print(
                f"[dim]  ↩  {_MAX_TOOL_ROUNDS} rounds atteints — synthèse forcée[/dim]"
            )
            llm_with_tools = factory()
        else:
            llm_with_tools = factory().bind_tools(selected_tools)

        messages = state["messages"]
        today = datetime.now().strftime("%Y-%m-%d")
        messages = _ensure_system_prompt(
            messages, selected_tools, today, plan_mode=plan_mode
        )

        # Proactive compression before calling the LLM (once per user turn max)
        working = messages
        _state_removals: list = []  # original msgs replaced by summary → RemoveMessage
        _summary_msg = None  # compressed SystemMessage to persist

        if _should_compress(working, backend) and not _compressed_this_turn:
            _compressed_this_turn = True
            console.print("[dim]  ↩  contexte chargé — compression proactive…[/dim]")
            _on_compress()
            plain_llm = factory()
            working = _cap_tool_messages(working)
            working, _state_removals = _compress_context(working, plain_llm, backend)
            before_tokens = _estimate_tokens(messages)
            after_tokens = _estimate_tokens(working)
            freed = before_tokens - after_tokens
            console.print(
                f"[dim]  ↩  compression: -{freed:,} tokens estimés "
                f"({before_tokens:,} → {after_tokens:,})[/dim]"
            )
            # Find compressed summary SystemMessage
            _summary_msg = next(
                (
                    m
                    for m in working
                    if isinstance(m, SystemMessage)
                    and _SUMMARY_MARKER in str(m.content)
                ),
                None,
            )

        if backend == "mistral":
            working = _sanitize_messages_for_mistral(working)

        capped = False
        compressed = False

        # Key pool tracking pour rotation sur 429
        _orch_provider = backend
        try:
            from src.llm.key_pool import get_pool as _get_pool

            _orch_key = _get_pool().next_healthy(backend) or ""
        except Exception:
            _orch_key = ""

        _RATE_LIMIT_MARKERS = (
            "429",
            "too many requests",
            "resource_exhausted",
            "rate limit",
            "quota exceeded",
            "session usage limit",
        )

        while True:
            try:
                response = llm_with_tools.invoke(working)

                usage = getattr(response, "usage_metadata", None)
                if usage:
                    from src.ui.token_gauge import update_usage

                    update_usage(usage)

                break

            except Exception as e:
                err = str(e).lower()

                # rotation vers la prochaine clef
                if any(k in err for k in _RATE_LIMIT_MARKERS):
                    try:
                        from src.llm.key_pool import get_fallback_order as _gfo
                        from src.llm.key_pool import get_pool as _kp

                        _nxt = _kp().next_provider_and_key(
                            _orch_provider, _orch_key, _gfo()
                        )
                        if _nxt:
                            _prev_provider = _orch_provider
                            _orch_provider, _orch_key = _nxt
                            settings.llm_backend = _orch_provider
                            # Bascule AUTOMATIQUE -> réversible au prochain tour.
                            from src.llm.key_pool import note_auto_fallback as _note
                            _note(_prev_provider, _orch_provider)
                            _new_llm = make_orchestrator_llm_with_key(
                                _orch_provider, _orch_key
                            )
                            llm_with_tools = (
                                _new_llm
                                if force_text
                                else _new_llm.bind_tools(selected_tools)
                            )
                            continue
                    except Exception:
                        pass
                    raise

                if "context" not in err and "length" not in err and "token" not in err:
                    raise

                if not capped:
                    capped = True
                    working = _cap_tool_messages(working)
                    console.print(
                        "[dim]  ↩  contexte trop long — tronquage des résultats tools…[/dim]"
                    )

                elif not compressed:
                    compressed = True
                    if not _compressed_this_turn:
                        _compressed_this_turn = True
                        _on_compress()
                    plain_llm = factory()
                    working, removed = _compress_context(working, plain_llm, backend)
                    before_tokens = _estimate_tokens(messages)
                    after_tokens = _estimate_tokens(working)
                    freed = before_tokens - after_tokens
                    console.print(
                        f"[dim]  ↩  compression: -{freed:,} tokens estimés "
                        f"({before_tokens:,} → {after_tokens:,})[/dim]"
                    )
                    _state_removals.extend(
                        r for r in removed if r not in _state_removals
                    )
                    _summary_msg = next(
                        (
                            m
                            for m in working
                            if isinstance(m, SystemMessage)
                            and _SUMMARY_MARKER in str(m.content)
                        ),
                        _summary_msg,
                    )
                    console.print("[dim]  ↩  contexte compressé — reprise…[/dim]")

                else:
                    reduced = _drop_smartest(working)
                    if reduced is None or len(reduced) <= 1:
                        raise
                    working = reduced
                    console.print(
                        f"[dim]  ↩  drop tool round ({len(working)} messages restants)…[/dim]"
                    )

        # Garde-fou : le LLM rappelle ask_clarification avec une question à laquelle
        # il a déjà une réponse dans cette conversation (le modèle ignore la réponse
        # qu'il vient de recevoir). Provoque une double popup identique côté utilisateur.
        # Détection + un seul retry pour lui faire utiliser la réponse déjà donnée.
        if not force_text:
            ask_calls = [
                tc for tc in (getattr(response, "tool_calls", None) or [])
                if tc.get("name") == "ask_clarification"
            ]
            if ask_calls:
                answered_questions: set[str] = set()
                for m in working:
                    if isinstance(m, ToolMessage) and getattr(m, "name", None) == "ask_clarification":
                        try:
                            content = m.content if isinstance(m.content, str) else json.dumps(m.content)
                            payload = json.loads(content)
                            for q_text in (payload.get("answers") or {}):
                                if q_text != "_extra":
                                    answered_questions.add(q_text.strip().lower())
                        except Exception:
                            pass

                is_duplicate = any(
                    (q.get("question") if isinstance(q, dict) else str(q) or "").strip().lower()
                    in answered_questions
                    for tc in ask_calls
                    for q in (tc.get("args", {}).get("questions") or [])
                )

                if is_duplicate:
                    console.print(
                        "[dim]  ↩  question déjà répondue reposée — correction…[/dim]"
                    )
                    dup_reminder = HumanMessage(
                        content=(
                            "[SYSTEME] Tu viens de reposer une question à laquelle tu as déjà "
                            "une réponse dans cette conversation (visible dans un précédent "
                            "résultat de ask_clarification). Utilise cette réponse directement, "
                            "ne la redemande pas. Continue l'action demandée avec les outils "
                            "appropriés."
                        )
                    )
                    try:
                        response = llm_with_tools.invoke(working + [response, dup_reminder])
                    except Exception:
                        pass  # échec de la correction → on garde la réponse originale

        # Garde-fou : certains modèles (minimax-m2.5 notamment, bug connu upstream)
        # écrivent parfois leur appel d'outil en texte brut ("xxx:tool_call ... "
        # "</xxx:tool_call>") au lieu du vrai mécanisme de function calling —
        # tool_calls reste vide et la commande n'est jamais exécutée. Détection +
        # un seul retry pour forcer un vrai appel structuré.
        if not force_text:
            no_real_tool_call = not getattr(response, "tool_calls", None)
            raw_text = _content_to_str(response.content)
            if no_real_tool_call and _MALFORMED_TOOL_CALL_RE.search(raw_text):
                console.print(
                    "[dim]  ↩  appel d'outil mal formé détecté — correction…[/dim]"
                )
                fix_reminder = HumanMessage(
                    content=(
                        "[SYSTEME] Ta dernière réponse contenait un faux appel d'outil "
                        "écrit en texte brut (une balise type 'xxx:tool_call ... "
                        "</xxx:tool_call>'). Cette syntaxe n'existe pas et n'exécute rien. "
                        "Refais le même appel en utilisant le vrai mécanisme de function "
                        "calling à ta disposition, pas du texte."
                    )
                )
                try:
                    response = llm_with_tools.invoke(working + [response, fix_reminder])
                except Exception:
                    pass  # échec de la correction → on garde la réponse originale

        # Garde-fou : le prompt interdit les questions en texte libre (elles doivent
        # passer par ask_clarification), mais rien n'empêche mécaniquement le LLM de
        # le faire quand même. Détection + un seul retry corrigé.
        # Exclus volontairement : les flows dont le design PRÉVOIT une confirmation
        # en texte libre ("brouillon + attends ton oui") — Slack (_SLACK) et le commit
        # git (_SHELL: "propose le message, attend la validation"), ainsi que le mode
        # plan (_PLAN_MODE: "wait for explicit validation"). Les intercepter casserait
        # ces flows volontairement conçus ainsi, ce qui serait pire que le bug d'origine.
        confirmation_flow_tools = {"slack_send_message", "git_commit"}
        has_confirmation_flow = any(t.name in confirmation_flow_tools for t in selected_tools)

        # L'utilisateur a-t-il DÉJÀ répondu à un questionnaire dans cette conversation ?
        # Si oui, reposer des questions en texte libre est TOUJOURS une erreur — même
        # dans un flow de confirmation (Slack/git). Sans cela, une simple demande
        # « poste sur le canal … » suffisait à désactiver le garde-fou, et le modèle
        # redemandait des informations déjà fournies (cas rapporté).
        _has_prior_answers = any(
            isinstance(m, ToolMessage) and getattr(m, "name", None) == "ask_clarification"
            and "answers" in (m.content if isinstance(m.content, str) else json.dumps(m.content))
            for m in working
        )
        if not force_text and not plan_mode and (not has_confirmation_flow or _has_prior_answers):
            no_tool_call = not getattr(response, "tool_calls", None)
            resp_text = _content_to_str(response.content).strip()
            # Une question en texte libre ne finit pas forcément par « ? » : le modèle
            # énumère souvent « 1 … 2 … 3 … » et termine par un point. On détecte donc
            # un « ? » N'IMPORTE OÙ, ou une demande explicite de précision.
            _looks_like_question = (
                resp_text.endswith("?")
                or "?" in resp_text
                or re.search(r"(?i)\b(veuillez préciser|merci de préciser|peux-tu préciser|"
                             r"il me (?:manque|faut)|precise[rz]|please specify)\b", resp_text)
            )
            if no_tool_call and _looks_like_question:
                console.print(
                    "[dim]  ↩  question en texte libre détectée — correction…[/dim]"
                )
                _answers_recap = ""
                if _has_prior_answers:
                    _pairs = []
                    for m in working:
                        if isinstance(m, ToolMessage) and getattr(m, "name", None) == "ask_clarification":
                            try:
                                _c = m.content if isinstance(m.content, str) else json.dumps(m.content)
                                for _q, _a in (json.loads(_c).get("answers") or {}).items():
                                    if _q != "_extra" and _a:
                                        _pairs.append(f"- {_q} -> {_a}")
                            except Exception:
                                pass
                    if _pairs:
                        _answers_recap = (
                            "\nRéponses DÉJÀ données par l'utilisateur (utilise-les, ne les "
                            "redemande pas) :\n" + "\n".join(_pairs)
                        )
                reminder = HumanMessage(
                    content=(
                        "[SYSTEME] Tu viens de répondre par une question en texte libre — "
                        "c'est interdit. Si l'info est déjà présente ailleurs dans cette "
                        "conversation (y compris une réponse précédente à ask_clarification), "
                        "utilise-la directement sans la redemander. Sinon, repose la question "
                        "immédiatement via ask_clarification(questions=[...])."
                        + _answers_recap
                    )
                )
                try:
                    _corrected = llm_with_tools.invoke(working + [response, reminder])
                    response = _corrected
                except Exception:
                    pass  # échec de la correction → on garde la réponse originale

        # Persist compression to LangGraph state so subsequent chatbot calls
        # start with the compressed history, not the original bloated one.
        from langchain_core.messages import RemoveMessage

        result: list = []
        if _state_removals:
            result += [
                RemoveMessage(id=m.id)
                for m in _state_removals
                if getattr(m, "id", None)
            ]
            if _summary_msg:
                result.append(_summary_msg)
        result.append(response)
        return {"messages": result}

    return chatbot, tools


def build_orchestrator():
    chatbot, tools = _chat_node_factory()

    g = StateGraph(GlobalState)
    g.add_node("chatbot", chatbot)
    g.add_node("tools", CachedToolNode(tools))

    g.add_edge(START, "chatbot")
    g.add_conditional_edges("chatbot", tools_condition)
    g.add_edge("tools", "chatbot")

    return g.compile(checkpointer=build_checkpointer())
