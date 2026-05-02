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
    coding_model_local: str = "qwen2.5-coder:14b"
    ollama_api_key: str | None = None

    # GROQ
    groq_model: str = "openai/gpt-oss-20b"
    groq_api_key: str | None = None

    # Gemini
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

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
    )


settings = _merge_yaml_into_settings()
