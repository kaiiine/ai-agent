from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from ..infra.settings import settings


def make_llm():
    """Ollama local."""
    return ChatOllama(
        model=settings.ollama_model,
        temperature=settings.temperature,
        num_ctx=131_072,
    )


def make_llm_ollama_cloud():
    """
    Ollama Cloud — deux modes :
    - Si OLLAMA_API_KEY est défini dans .env → API distante sur https://ollama.com
    - Sinon → modèle cloud local (nécessite `ollama signin`)
      Le modèle doit se terminer par `-cloud` (ex: gpt-oss:120b-cloud)
    """
    if settings.ollama_api_key:
        # API distante ollama.com — modèle sans suffixe -cloud
        model = settings.ollama_cloud_model.removesuffix("-cloud")
        return ChatOllama(
            model=model,
            base_url="https://ollama.com",
            headers={"Authorization": f"Bearer {settings.ollama_api_key}"},
            temperature=settings.temperature,
        )
    else:
        # Ollama local avec offload cloud (après `ollama signin`)
        cloud_model = settings.ollama_cloud_model
        return ChatOllama(
            model=cloud_model,
            temperature=settings.temperature,
        )


def make_coding_llm():
    """Coding specialist — en local réutilise le même modèle que l'orchestrateur."""
    if settings.llm_backend == "ollama":
        # Même modèle que l'orchestrateur → pas de double chargement en RAM
        return ChatOllama(model=settings.ollama_model, temperature=0.0)
    elif settings.llm_backend == "groq":
        return ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=0.0,
            max_tokens=8192,
            streaming=True,
        )
    else:
        return ChatOllama(model=settings.coding_model, temperature=0.0)


def make_llm_groq():
    """Groq cloud — llama/deepseek via API."""
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=settings.temperature,
        max_tokens=8192,
        streaming=True,
    )