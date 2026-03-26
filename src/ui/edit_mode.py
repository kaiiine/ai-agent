"""Edit mode for the coding agent: 'ask' (HITL per-file) or 'auto' (write without confirmation)."""

_mode = "ask"  # default


def get_mode() -> str:
    return _mode


def set_mode(mode: str) -> bool:
    global _mode
    if mode in ("ask", "auto"):
        _mode = mode
        return True
    return False
