from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from ..infra.settings import settings

def make_llm():
    return ChatOllama(
        model=settings.ollama_model,
        temperature=settings.temperature,
        streaming=False,  
        num_ctx=131072,  
    )

def make_llm_groq():
    
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=settings.temperature,
        max_tokens=8192,
        streaming=True,

    )