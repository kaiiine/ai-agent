# src/orchestrator/provider_quirks.py
"""Contournements de comportements SPÉCIFIQUES à un fournisseur.

Isolés ici pour deux raisons : le flux principal reste lisible sans eux, et
chacun porte la trace de ce qu'il contourne — un contournement dont on a oublié
la cause ne s'enlève jamais.
"""
from __future__ import annotations

import re
from typing import List

from langchain_core.messages import AIMessage, ToolMessage

_MALFORMED_TOOL_CALL_RE = re.compile(r"\w+:tool_call\b.*?</\w+:tool_call>", re.DOTALL | re.IGNORECASE)

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
