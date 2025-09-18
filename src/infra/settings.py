# src/infra/settings.py
import os, yaml
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # LLM
    ollama_model: str = "qwen2.5:7b"
    temperature: float = 0.0

    # Search
    search_backend: str = "tavily"
    search_max_results: int = 2

    # CLI
    cli_thread_id: str = "1"

    # 🔑 Clés optionnelles (chargées depuis l'env si présentes)
    openai_api_key: str | None = None
    google_api_key: str | None = None
    tavily_api_key: str | None = None

    # Pydantic v2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="allow",          # ← ignore/autorise toute autre variable d'env inconnue
    )

def _find_config_path() -> Path | None:
    if os.getenv("APP_CONFIG"):
        p = Path(os.getenv("APP_CONFIG")).expanduser().resolve()
        if p.is_file(): return p
    root = Path(__file__).resolve().parents[2]
    for name in ("base.yaml", "base.yml"):
        p = root / "configs" / name
        if p.is_file(): return p
    return None

def _load_yaml_config() -> dict:
    p = _find_config_path()
    if not p: return {}
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
        # Pas besoin de passer les API keys ici : BaseSettings va
        # les prendre automatiquement depuis l'environnement.
    )

settings = _merge_yaml_into_settings()
