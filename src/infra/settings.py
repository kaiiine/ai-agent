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
    ollama_cloud_api_keys: str = "" # OLLAMA_CLOUD_API_KEYS=key1,key2,key3,key4,key5
      

    # Coding specialist (delegated coding tasks)
    # Même valeur que `configs/base.yaml`. Les deux avaient divergé : le défaut
    # Python ne sert que si le YAML manque, donc l'écart ne se voyait jamais —
    # jusqu'au jour où le YAML manque.
    coding_model: str = "gpt-oss:120b-cloud"
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

    # Nvidia
    nvidia_api_key: str | None = None
    nvidia_model: str = "meta/muse-glimmer-30b"
    nvidia_coding_model: str = ""
    nvidia_api_keys: str = ""

    # OpenRouter — compatible OpenAI, 21 modèles à 0 € au relevé du catalogue.
    # Les `:free` ont un quota partagé et peuvent renvoyer 429 : le pool de clés
    # et l'ordre de repli servent ici comme ailleurs.
    openrouter_api_key: str | None = None
    openrouter_model: str = "minimax/minimax-m3:free"
    openrouter_coding_model: str = "minimax/minimax-m3:free"
    openrouter_api_keys: str = ""     # OPENROUTER_API_KEYS=key1,key2,...
    openrouter_base_url: str = "https://openrouter.ai/api/v1"



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

    # Aperçu ASCII du navigateur (src/ui/ascii)
    #
    # Désactivable parce qu'un aperçu est un confort : sur un terminal sans
    # couleurs vraies, dans un CI, ou quand on veut le silence, il doit pouvoir
    # disparaître sans que rien d'autre ne change. À False, aucun fil n'est
    # lancé et aucune capture n'est demandée — ce n'est pas un affichage masqué,
    # c'est un sidecar absent.
    apercu_navigateur: bool = True
    #: "" laisse le registre choisir le meilleur moteur présent. Un nom inconnu
    #: n'est pas une erreur : on retombe sur l'ordre par défaut.
    apercu_moteur: str = ""
    apercu_colonnes: int = 72
    apercu_lignes: int = 20
    #: Largeur de la colonne d'aperçu ancrée à droite, en cellules. Mettre
    #: `apercu_colonnes: 0` revient à l'affichage classique, qui défile et garde
    #: tout l'historique du terminal — l'ancrage, lui, redessine sa surface et
    #: perd les lignes sorties du journal.
    apercu_largeur: int = 46
    #: Rythme de capture spontanée, en secondes. 0 = purement événementiel (une
    #: image par action navigateur, ce qui donnait UNE image par phase).
    #: L'intervalle double tout seul tant que l'image ne change pas, et repart au
    #: minimum dès qu'elle bouge : une page figée ne coûte presque rien.
    apercu_battement: float = 1.2
    apercu_battement_max: float = 20.0

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
        coding_model=yml.get("coding_model", "minimax-m3:cloud"),
        gemini_model=yml.get("gemini", {}).get("model", "gemini-2.5-flash"),
        gemini_coding_model=yml.get("gemini", {}).get("coding_model", "gemini-2.5-flash"),
        mistral_model=yml.get("mistral", {}).get("model", "mistral-small-2603"),
        mistral_coding_model=yml.get("mistral", {}).get("coding_model", "codestral-2508"),
        nvidia_model=yml.get("nvidia", {}).get("model", "meta/muse-glimmer-30b"),
        nvidia_coding_model=yml.get("nvidia", {}).get("coding_model", "meta/muse-glimmer-30b")
    )


settings = _merge_yaml_into_settings()
