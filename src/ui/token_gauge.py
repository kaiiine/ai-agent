# src/ui/token_gauge.py

from __future__ import annotations

# ── State ──────────────────────────────────────────────────────────────────────
_input_tokens: int = 0
_output_tokens: int = 0

# Les fenêtres de contexte viennent de `orchestrator.context` : la jauge et le
# seuil de compression doivent répondre la MÊME chose à « où en est-on de la
# fenêtre ». Deux tables séparées finissaient par diverger, et l'utilisateur
# voyait alors 60 % pendant qu'une compression se déclenchait.
from src.orchestrator.context import _CONTEXT_LIMIT_DEFAUT, _CONTEXT_LIMITS

# ── Public API ─────────────────────────────────────────────────────────────────

def update_usage(usage_metadata: dict | None) -> None:
    """Update counters from a LangChain usage_metadata dict."""
    global _input_tokens, _output_tokens
    if not usage_metadata:
        return
    _input_tokens  = usage_metadata.get("input_tokens", _input_tokens)
    _output_tokens = usage_metadata.get("output_tokens", _output_tokens)


def reset() -> None:
    global _input_tokens, _output_tokens
    _input_tokens = _output_tokens = 0


def has_tokens() -> bool:
    return _input_tokens > 0


def get_ratio(backend: str = "ollama_cloud") -> float:
    limit = _CONTEXT_LIMITS.get(backend, _CONTEXT_LIMIT_DEFAUT)
    return min(_input_tokens / limit, 1.0)


def gauge_markup(backend: str = "ollama_cloud") -> str:
    """
    Returns a Rich markup string like:  [yellow]◑[/yellow] [dim]51%[/dim]
    The circle fills from ○ to ● and changes colour as it fills.
    """
    ratio = get_ratio(backend)
    pct   = int(ratio * 100)

    if ratio < 0.12:
        char = "○"
    elif ratio < 0.37:
        char = "◔"
    elif ratio < 0.62:
        char = "◑"
    elif ratio < 0.87:
        char = "◕"
    else:
        char = "●"

    if ratio < 0.50:
        color = "green"
    elif ratio < 0.75:
        color = "yellow"
    elif ratio < 0.90:
        color = "color(214)"  
    else:
        color = "red"

    return f"[{color}]{char}[/{color}] [dim]{pct}%[/dim]"
