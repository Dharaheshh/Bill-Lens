from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://billlens:billlens@localhost:5433/billlens"
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL_VISION: str = ""
    LLM_MODEL_AGENT: str = ""
    LLM_MODEL_FAST: str = ""
    LLM_FALLBACK_BASE_URL: str = ""
    LLM_FALLBACK_API_KEY: str = ""
    LLM_FALLBACK_MODEL: str = ""
    LLM_CACHE_MODE: str = "readwrite"
    EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBED_DIM: int = 384
    FASTEMBED_CACHE_PATH: str = "/app/.fastembed"
    PRICE_VARIANCE_FACTOR: float = 1.5
    ESTIMATE_VARIANCE_FACTOR: float = 1.2
    ALLOWED_ORIGINS: str = "http://localhost:5173"
    STORAGE_DIR: str = "./storage"
    REPLAY_MAX_GAP_MS: int = 1200

    class Config:
        env_file = ".env"

settings = Settings()
