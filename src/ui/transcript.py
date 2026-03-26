import os
from datetime import datetime

def save_transcript(thread_id: str, state: dict) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = f"transcripts/{thread_id}-{ts}.md"
    os.makedirs("transcripts", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for m in state.get("messages", []):
            role = m.get("role", "assistant")
            content = m.get("content", "")
            f.write(f"### {role}\n\n{content}\n\n---\n\n")
    return path
