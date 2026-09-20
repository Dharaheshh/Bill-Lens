
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://billlens:billlens@localhost:5433/billlens"
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL_VISION: str = "gpt-4o"
    LLM_MODEL_AGENT: str = "gpt-4o-mini"
    LLM_MODEL_FAST: str = "gpt-4o-mini"
    LLM_VISION_BASE_URL: str = ""
    LLM_VISION_API_KEY: str = ""
    LLM_FALLBACK_BASE_URL: str = ""
    LLM_FALLBACK_API_KEY: str = ""
    LLM_FALLBACK_MODEL: str = ""
    LLM_CACHE_MODE: str = "readwrite"
    EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBED_DIM: int = 384
    FASTEMBED_CACHE_PATH: str = "./fastembed_cache"
    PRICE_VARIANCE_FACTOR: float = 1.5
    ESTIMATE_VARIANCE_FACTOR: float = 1.2
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    STORAGE_DIR: str = "./storage"
    REPLAY_MAX_GAP_MS: int = 1200

    class Config:
        env_file = ".env"

settings = Settings()
