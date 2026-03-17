from dataclasses import dataclass, field

@dataclass
class SessionConfig:
    thread_id: str = "user_session"
    model: str = "lfm2:latest"  
    temp: float = 0.0
    lang_pref: str = "fr"   
    depth_search: bool = False 

def fmt_ms(s: float) -> str:
    return f"{s*1000:,.0f} ms"
