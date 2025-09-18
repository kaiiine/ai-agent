from langchain_ollama import ChatOllama
from ..infra.settings import settings

def make_llm():
    return ChatOllama(
        model=settings.ollama_model,
        temperature=settings.temperature,
        streaming=True,
    )
