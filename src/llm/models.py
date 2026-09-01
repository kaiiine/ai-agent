from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from ..infra.settings import settings


_REQUEST_TIMEOUT = 180.0
_OLLAMA_CLIENT_KWARGS = {"timeout": _REQUEST_TIMEOUT}


def _ollama_cloud_kwargs(key: str) -> dict:
    """Options client pour ollama.com, AVEC la clé d'API réellement transmise.

    `ChatOllama` déclare `extra="ignore"` : un `headers=...` passé à son
    constructeur est SILENCIEUSEMENT jeté. Aucune erreur, aucun avertissement —
    et chaque requête retombait alors sur l'identité machine
    `~/.ollama/id_ed25519`, c'est-à-dire TOUJOURS le même compte, quel que soit
    le nombre de clés du pool.

    Mesuré : sur cinq clés de cinq comptes différents, une seule était jamais
    sollicitée — celle de la machine — et son quota hebdomadaire saturait
    pendant que les quatre autres restaient à 0 %. Une clé volontairement bidon
    passait tout de même, ce qui prouvait qu'elle n'était pas lue.

    Le seul chemin qui arrive jusqu'à la requête est `client_kwargs`, transmis
    tel quel à `ollama.Client(**kwargs)` puis à httpx.
    """
    kwargs = dict(_OLLAMA_CLIENT_KWARGS)
    if key:
        kwargs["headers"] = {"Authorization": f"Bearer {key}"}
    return kwargs
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


def cle_ollama_cloud() -> str:
    """La clé à employer pour ollama.com, dans l'ordre de préférence.

    Le dernier recours est la PREMIÈRE clé configurée, même en cooldown — jamais
    la chaîne vide. Un client sans clé ne lève aucune erreur : le paquet `ollama`
    signe alors la requête avec l'identité machine `~/.ollama/id_ed25519`, donc
    sur le compte auquel le poste est connecté. On croyait tourner sur cinq
    comptes, tout partait sur un seul, et son quota saturait pendant que les
    autres restaient intacts.

    Un cooldown est une mémoire locale de quelques dizaines de minutes, pas une
    preuve : mieux vaut une clé peut-être fatiguée qu'un compte qu'on ne
    surveille pas.
    """
    try:
        from src.llm.key_pool import get_pool
        pool = get_pool()
        return (pool.next_healthy("ollama_cloud")
                or settings.ollama_api_key
                or next(iter(pool.keys_for("ollama_cloud") or []), "")
                or "")
    except Exception:
        return settings.ollama_api_key or ""


def make_llm_ollama_cloud():
    """Ollama Cloud — clé issue du pool, jamais l'identité machine par défaut."""
    return ChatOllama(
        model=settings.ollama_cloud_model.removesuffix("-cloud"),
        base_url="https://ollama.com",
        client_kwargs=_ollama_cloud_kwargs(cle_ollama_cloud()),
        temperature=settings.temperature,
        num_ctx=_OLLAMA_NUM_CTX,
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
            client_kwargs=_ollama_cloud_kwargs(key),
            temperature=0.0,
            num_ctx=_OLLAMA_NUM_CTX,
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
    elif provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        return ChatNVIDIA(
            model=settings.nvidia_coding_model or settings.nvidia_model,
            api_key=key,
            temperature=0.0,
            max_completion_tokens=8192,
        )
    elif provider == "groq":
        return ChatGroq(
            api_key=key,
            model=settings.groq_model,
            temperature=0.0,
            max_tokens=8192,
            streaming=True,
        )
    elif provider == "openrouter":
        return _openrouter(settings.openrouter_coding_model, key)
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
        if not key:
            # Aucune clé « saine » : on prend quand même la première configurée.
            # Le repli legacy ci-dessous construit sinon un client SANS clé, qui
            # s'authentifie avec l'identité machine et masque le vrai compte.
            key = next(iter(pool.keys_for(settings.llm_backend) or []), "")
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
    elif settings.llm_backend == "openrouter":
        return _openrouter(settings.openrouter_coding_model,
                           settings.openrouter_api_key or "")
    elif settings.llm_backend == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        return ChatNVIDIA(
            model=settings.nvidia_coding_model or settings.nvidia_model,
            api_key=settings.nvidia_api_key,
            temperature=0.0,
            max_completion_tokens=8192,
        )
    else:
        # ollama_cloud
        coding_model = settings.coding_model
        if settings.ollama_api_key:
            return ChatOllama(
                model=coding_model.removesuffix("-cloud"),
                base_url="https://ollama.com",
                client_kwargs=_ollama_cloud_kwargs(settings.ollama_api_key),
                temperature=0.0,
                num_ctx=_OLLAMA_NUM_CTX,
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
            client_kwargs=_ollama_cloud_kwargs(key),
            temperature=settings.temperature,
            num_ctx=_OLLAMA_NUM_CTX,
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
    elif provider == "nvidia":
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        return ChatNVIDIA(
            model=settings.nvidia_model, api_key=key,
            temperature=settings.temperature, max_completion_tokens=8192,
        )
    elif provider == "groq":
        return ChatGroq(
            api_key=key, model=settings.groq_model,
            temperature=settings.temperature, max_tokens=8192, streaming=True,
        )
    elif provider == "openrouter":
        return _openrouter(settings.openrouter_model, key)
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

def make_llm_nvidia():
    try:
        from src.llm.key_pool import get_pool
        key = get_pool().next_healthy("nvidia")
        if key:
            from langchain_nvidia_ai_endpoints import ChatNVIDIA
            return ChatNVIDIA(
                model=settings.nvidia_model,
                api_key=key, 
                temperature=settings.temperature,
                max_completion_tokens=8192,
            )
    except Exception:
        pass
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    return ChatNVIDIA(
        model=settings.nvidia_model,
        api_key=settings.nvidia_api_key, 
        temperature=settings.temperature,
        max_completion_tokens=8192,
    )


def _openrouter(modele: str, cle: str):
    """Client OpenRouter — compatible OpenAI, donc `ChatOpenAI` avec sa base.

    Les en-têtes `HTTP-Referer` et `X-Title` sont ce qu'OpenRouter attend pour
    attribuer l'usage : facultatifs, mais les omettre range les requêtes parmi
    les anonymes.
    """
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=modele,
        api_key=cle,
        base_url=settings.openrouter_base_url,
        temperature=settings.temperature,
        streaming=True,
        timeout=_REQUEST_TIMEOUT,
        max_retries=_CLIENT_MAX_RETRIES,
        default_headers={"HTTP-Referer": "https://github.com/kaine/axon",
                         "X-Title": "AXON"},
    )


def make_llm_openrouter():
    """OpenRouter — pool de clés d'abord, clé unique ensuite.

    Même contrat que les autres fournisseurs : un quota `:free` saturé sur une
    clé n'immobilise pas les suivantes.
    """
    try:
        from src.llm.key_pool import get_pool

        cle = get_pool().next_healthy("openrouter")
        if cle:
            return _openrouter(settings.openrouter_model, cle)
    except Exception:                                        # noqa: BLE001
        pass
    return _openrouter(settings.openrouter_model, settings.openrouter_api_key or "")
