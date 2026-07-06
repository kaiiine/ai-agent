from __future__ import annotations

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str | list  # Zed envoie parfois une liste de blocs {type, text}

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in self.content
        )


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    stream: bool = True
    model: str = "axon"
