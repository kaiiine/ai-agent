# src/infra/settings.py
import os
import yaml
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # LLM local
    ollama_model: str = "lfm2:latest"
    temperature: float = 0.0

    # Ollama Cloud
    ollama_cloud_model: str = "gpt-oss:120b-cloud"

    # Coding specialist (delegated coding tasks)
    coding_model: str = "qwen3-coder-next:cloud"
    coding_model_local: str = "qwen2.5-coder:7b"
    coding_num_ctx_local: int = 16_384   # KV cache local — ajuster selon VRAM GPU (.env: CODING_NUM_CTX_LOCAL=8192)
    ollama_api_key: str | None = None

    # GROQ
    groq_model: str = "openai/gpt-oss-20b"
    groq_api_key: str | None = None
    groq_api_keys: str = ""          # GROQ_API_KEYS=key1,key2,...

    # Gemini
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_coding_model: str = "gemini-2.5-flash"  # specialist can use a stronger model
    gemini_api_keys: str = ""        # GEMINI_API_KEYS=key1,key2,...

    # Mistral
    mistral_api_key: str | None = None
    mistral_model: str = "mistral-small-2603"
    mistral_coding_model: str = "codestral-2508"
    mistral_api_keys: str = ""       # MISTRAL_API_KEYS=key1,key2,...

    # Multi-clés ollama cloud
    ollama_cloud_api_keys: str = ""  # OLLAMA_CLOUD_API_KEYS=key1,key2,key3,key4,key5

    # Ordre de fallback inter-providers : FALLBACK_ORDER=ollama_cloud,gemini,mistral
    fallback_order: str = "ollama_cloud,gemini,mistral"

    # Search
    search_backend: str = "tavily"
    search_max_results: int = 10
    tavily_api_key: str | None = None

    # Backend LLM actif : "groq" | "ollama" | "ollama_cloud"
    llm_backend: str = "ollama_cloud"

    # CLI
    cli_thread_id: str = "1"

    # Dossier racine des projets (utilisé par find_git_repos, local_find_file, git tools)
    # Laisser vide → l'IA cherchera depuis $HOME
    projects_dir: str = ""

    # Clés optionnelles
    openai_api_key: str | None = None
    google_api_key: str | None = None
    slack_bot_token: str | None = None

    # Pydantic v2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="allow",
    )


def _find_config_path() -> Path | None:
    if os.getenv("APP_CONFIG"):
        p = Path(os.getenv("APP_CONFIG")).expanduser().resolve()
        if p.is_file():
            return p
    root = Path(__file__).resolve().parents[2]
    for name in ("base.yaml", "base.yml"):
        p = root / "configs" / name
        if p.is_file():
            return p
    return None


def _load_yaml_config() -> dict:
    p = _find_config_path()
    if not p:
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _merge_yaml_into_settings() -> Settings:
    yml = _load_yaml_config()
    return Settings(
        ollama_model=yml.get("ollama", {}).get("model", "qwen2.5:7b"),
        temperature=yml.get("ollama", {}).get("temperature", 0.0),
        search_backend=yml.get("search", {}).get("backend", "tavily"),
        search_max_results=yml.get("search", {}).get("max_results", 2),
        cli_thread_id=yml.get("cli", {}).get("thread_id", "1"),
        groq_model=yml.get("groq", {}).get("model", "openai/gpt-oss-20b"),
        llm_backend=yml.get("llm_backend", "ollama_cloud"),
        coding_model=yml.get("coding_model", "qwen3-coder-next:cloud"),
        gemini_model=yml.get("gemini", {}).get("model", "gemini-2.5-flash"),
        gemini_coding_model=yml.get("gemini", {}).get("coding_model", "gemini-2.5-flash"),
        mistral_model=yml.get("mistral", {}).get("model", "mistral-small-2603"),
        mistral_coding_model=yml.get("mistral", {}).get("coding_model", "codestral-2508"),
    )


settings = _merge_yaml_into_settings()
