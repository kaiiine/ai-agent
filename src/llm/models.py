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
    - si OLLAMA_API_KEY est défini dans .env
    - sinon → modèle cloud local 
      le modèle doit se terminer par `-cloud` 
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
        cloud_model = settings.ollama_cloud_model
        return ChatOllama(
            model=cloud_model,
            temperature=settings.temperature,
        )


def _ollama_unload(model: str, base_url: str = "http://localhost:11434") -> None:
    """Unload a model from VRAM by setting keep_alive=0."""
    import requests
    try:
        requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=10,
        )
    except Exception:
        pass


def make_coding_llm():
    """Coding specialist — uses dedicated coding model with VRAM swap on local ollama."""
    if settings.llm_backend == "ollama":
        return ChatOllama(model=settings.coding_model_local, temperature=0.0, num_ctx=131_072)
    elif settings.llm_backend == "groq":
        return ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=0.0,
            max_tokens=8192,
            streaming=True,
        )
    elif settings.llm_backend == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=0.0,
            max_output_tokens=8192,
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


def make_llm_gemini():
    """Google Gemini — gratuit, 1M tokens de contexte."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=settings.temperature,
        max_output_tokens=8192,
        streaming=True,
    )