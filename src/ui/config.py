from dataclasses import dataclass, field

@dataclass
class SessionConfig:
    thread_id: str = "user_session"
    model: str = "qwen2.5:7b"  # indicatif (hot-swap si tu rebuildes le graphe)
    temp: float = 0.0
    lang_pref: str = "auto"    # "fr" | "en" | "auto"

def fmt_ms(s: float) -> str:
    return f"{s*1000:,.0f} ms"
