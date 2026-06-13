"""
SNO Application Configuration
Uses pydantic-settings (v2) for env-var loading with fallback defaults.
"""
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database (defaults to local SQLite for development) ──
    DATABASE_URL: str = "sqlite:///./sno_state.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Knowledge Nexus ──────────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    NEO4J_URL: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # ── LLM API Keys ─────────────────────────────────────────
    OPENAI_API_KEY: Optional[str] = None
    CLAUDE_API_KEY: Optional[str] = None

    # ── SNO Runtime ──────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    SNO_VERSION: str = "1.0.0-beta"

    # FIX: Use Pydantic v2 model_config dict instead of inner class Config.
    # The old `class Config: env_file = ".env"` syntax is Pydantic v1 and
    # raises a deprecation warning in pydantic-settings>=2.0.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",   # Silently ignore unknown env vars
    }


settings = Settings()