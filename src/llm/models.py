from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from ..infra.settings import settings


_REQUEST_TIMEOUT = 180.0
_OLLAMA_CLIENT_KWARGS = {"timeout": _REQUEST_TIMEOUT}
_OLLAMA_NUM_CTX = 131_072
_CLIENT_MAX_RETRIES = 2


def make_llm():
    """Ollama local."""
    return ChatOllama(
        model=settings.ollama_model,
        temperature=settings.temperature,
        num_ctx=_OLLAMA_NUM_CTX,
        client_kwargs=_OLLAMA_CLIENT_KWARGS,
    )


def make_llm_ollama_cloud():
    """
    Ollama Cloud — utilise le key pool si disponible, sinon clé unique legacy.
    """
    try:
        from src.llm.key_pool import get_pool
        key = get_pool().next_healthy("ollama_cloud")
        if key:
            model = settings.ollama_cloud_model.removesuffix("-cloud")
            return ChatOllama(
                model=model,
                base_url="https://ollama.com",
                headers={"Authorization": f"Bearer {key}"},
                temperature=settings.temperature,
                num_ctx=_OLLAMA_NUM_CTX,
                client_kwargs=_OLLAMA_CLIENT_KWARGS,
            )
    except Exception:
        pass

    # Fallback : clé unique depuis settings
    if settings.ollama_api_key:
        model = settings.ollama_cloud_model.removesuffix("-cloud")
        return ChatOllama(
            model=model,
            base_url="https://ollama.com",
            headers={"Authorization": f"Bearer {settings.ollama_api_key}"},
            temperature=settings.temperature,
            num_ctx=_OLLAMA_NUM_CTX,
            client_kwargs=_OLLAMA_CLIENT_KWARGS,
        )
    return ChatOllama(model=settings.ollama_cloud_model, temperature=settings.temperature,
                      num_ctx=_OLLAMA_NUM_CTX, client_kwargs=_OLLAMA_CLIENT_KWARGS)


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


def make_coding_llm_with_key(provider: str, key: str):
    """
    Crée un LLM de coding pour un provider et une clé spécifiques.
    Utilisé par le key pool pour basculer entre clés/providers sans relancer la session.
    """
    if provider in ("ollama_cloud", "ollama"):
        if provider == "ollama" and not key:
            return ChatOllama(
                model=settings.coding_model_local,
                temperature=0.0,
                num_ctx=settings.coding_num_ctx_local,
                client_kwargs=_OLLAMA_CLIENT_KWARGS,
            )
        coding_model = settings.coding_model.removesuffix("-cloud")
        return ChatOllama(
            model=coding_model,
            base_url="https://ollama.com",
            headers={"Authorization": f"Bearer {key}"},
            temperature=0.0,
            num_ctx=_OLLAMA_NUM_CTX,
            client_kwargs=_OLLAMA_CLIENT_KWARGS,
        )
    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_coding_model,
            google_api_key=key,
            temperature=0.0,
            max_output_tokens=32768,
            timeout=_REQUEST_TIMEOUT,
            max_retries=_CLIENT_MAX_RETRIES,
        )
    elif provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(
            model=settings.mistral_coding_model,
            mistral_api_key=key,
            temperature=0.0,
            timeout=_REQUEST_TIMEOUT,
            max_retries=_CLIENT_MAX_RETRIES,
        )
    elif provider == "groq":
        return ChatGroq(
            api_key=key,
            model=settings.groq_model,
            temperature=0.0,
            max_tokens=8192,
            streaming=True,
        )
    else:
        return make_coding_llm()


def make_coding_llm():
    """Coding specialist — utilise le key pool pour choisir la première clé saine."""
    # Local ollama : pas de key pool
    if settings.llm_backend == "ollama":
        return ChatOllama(
            model=settings.coding_model_local,
            temperature=0.0,
            num_ctx=settings.coding_num_ctx_local,
            client_kwargs=_OLLAMA_CLIENT_KWARGS,
        )

    # Pour tous les backends cloud, essaie d'abord via key pool
    try:
        from src.llm.key_pool import get_pool
        pool = get_pool()
        key = pool.next_healthy(settings.llm_backend)
        if key:
            return make_coding_llm_with_key(settings.llm_backend, key)
    except Exception:
        pass

    # Fallback : comportement legacy (clé unique depuis settings)
    if settings.llm_backend == "groq":
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
            model=settings.gemini_coding_model,
            google_api_key=settings.gemini_api_key,
            temperature=0.0,
            max_output_tokens=32768,
            timeout=_REQUEST_TIMEOUT,
            max_retries=_CLIENT_MAX_RETRIES,
        )
    elif settings.llm_backend == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(
            model=settings.mistral_coding_model,
            mistral_api_key=settings.mistral_api_key,
            temperature=0.0,
            timeout=_REQUEST_TIMEOUT,
            max_retries=_CLIENT_MAX_RETRIES,
        )
    else:
        # ollama_cloud
        coding_model = settings.coding_model
        if settings.ollama_api_key:
            return ChatOllama(
                model=coding_model.removesuffix("-cloud"),
                base_url="https://ollama.com",
                headers={"Authorization": f"Bearer {settings.ollama_api_key}"},
                temperature=0.0,
                num_ctx=_OLLAMA_NUM_CTX,
                client_kwargs=_OLLAMA_CLIENT_KWARGS,
            )
        return ChatOllama(model=coding_model, temperature=0.0,
                          num_ctx=_OLLAMA_NUM_CTX, client_kwargs=_OLLAMA_CLIENT_KWARGS)


def make_orchestrator_llm_with_key(provider: str, key: str):
    """
    Crée un LLM orchestrateur pour un provider/clé spécifiques.
    Utilisé par le key pool pour basculer après 429, sans toucher aux modèles coding.
    """
    if provider in ("ollama_cloud", "ollama"):
        if provider == "ollama" and not key:
            return ChatOllama(model=settings.ollama_model, temperature=settings.temperature,
                              num_ctx=_OLLAMA_NUM_CTX, client_kwargs=_OLLAMA_CLIENT_KWARGS)
        model = settings.ollama_cloud_model.removesuffix("-cloud")
        return ChatOllama(
            model=model,
            base_url="https://ollama.com",
            headers={"Authorization": f"Bearer {key}"},
            temperature=settings.temperature,
            num_ctx=_OLLAMA_NUM_CTX,
            client_kwargs=_OLLAMA_CLIENT_KWARGS,
        )
    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=key,
            temperature=settings.temperature,
            max_output_tokens=8192,
            streaming=True,
            thinking_budget=0,
            timeout=_REQUEST_TIMEOUT,
            max_retries=_CLIENT_MAX_RETRIES,
        )
    elif provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(model=settings.mistral_model, mistral_api_key=key,
                             temperature=0.0, streaming=True, timeout=_REQUEST_TIMEOUT,
                             max_retries=_CLIENT_MAX_RETRIES)
    elif provider == "groq":
        return ChatGroq(
            api_key=key, model=settings.groq_model,
            temperature=settings.temperature, max_tokens=8192, streaming=True,
        )
    else:
        return make_llm_ollama_cloud()


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
    """Google Gemini — key pool first, then single-key fallback."""
    try:
        from src.llm.key_pool import get_pool
        key = get_pool().next_healthy("gemini")
        if key:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=settings.gemini_model, google_api_key=key,
                temperature=settings.temperature, max_output_tokens=8192,
                streaming=True, thinking_budget=0, timeout=_REQUEST_TIMEOUT,
                max_retries=_CLIENT_MAX_RETRIES,
            )
    except Exception:
        pass
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=settings.temperature,
        max_output_tokens=8192,
        streaming=True,
        thinking_budget=0,
        timeout=_REQUEST_TIMEOUT,
        max_retries=_CLIENT_MAX_RETRIES,
    )


def make_llm_mistral():
    """Mistral — key pool first, then single-key fallback."""
    try:
        from src.llm.key_pool import get_pool
        key = get_pool().next_healthy("mistral")
        if key:
            from langchain_mistralai import ChatMistralAI
            return ChatMistralAI(model=settings.mistral_model, mistral_api_key=key,
                             temperature=0.0, streaming=True, timeout=_REQUEST_TIMEOUT,
                             max_retries=_CLIENT_MAX_RETRIES)
    except Exception:
        pass
    from langchain_mistralai import ChatMistralAI
    return ChatMistralAI(model=settings.mistral_model,
                         mistral_api_key=settings.mistral_api_key,
                         temperature=0.0, streaming=True, timeout=_REQUEST_TIMEOUT,
                             max_retries=_CLIENT_MAX_RETRIES)